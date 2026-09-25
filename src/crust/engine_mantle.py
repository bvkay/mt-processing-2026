# -*- coding: utf-8 -*-
"""
MANTLE as a second transfer-function engine behind process_rr.py

`process_pair` reads the local and remote processing archives over the
window through MANTLE's MTH5 reader (`io.mth5_reader`, which hands `run_site`
the channels in MANTLE's own units and signs, so a filtered variant is used
as it stands), runs the validated cascade in remote-reference robust mode
with the configuration MANTLE's site runner applies to LEMI-423 records
(block jackknife of 8, the native level capped at 2 M samples, prewhitening
off, the coil curve of the archives deconvolved in the spectral domain) and
writes three products beside the aurora ones: MANTLE's fine-grid EDI and
report JSON, and the EDI on the survey's band scheme that the GUI, the
campaign and the comparison figure read.

The band EDI pools MANTLE's per-bin impedance onto the band edges of
`crust.bands.build_band_scheme`: the plain complex mean of the bins each
band holds, the band's period the geometric centre as aurora's, and the
variance of each band mean from the within-band jackknife covariance
(`JackknifeResult.covariance`, block-diagonal over the cascade bands, the
quadratic form `processing.pooling` uses). `levels_for` picks the cascade
depth the window supports. The keys `sidecar_extras` adds to the run's
sidecar are `engine`, `engine_version`, `engine_config`, `mantle_report`
and `mantle_fine_edi`.

The cascade holds the whole window in memory, so `check_window` refuses a
window longer than `MantleOptions.max_hours` (MAX_HOURS, 24 h, by default).
Its peak is about GB_PER_HOUR (1.35) GB per hour of window at 1000 Hz with
six channels, as measured on a 23.5 h window (31.8 GB); a limit above 24 h
logs one warning line with the peak `expected_peak_gb` gives for the
window.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from loguru import logger
from mt_metadata.transfer_functions.core import TF

from . import _mantle

ENGINE = "mantle"
WHITEN = ("none", "diff")
MAX_LEVELS = 8
MAX_HOURS = 24.0  # the default window limit (MantleOptions.max_hours, process_rr.py --mantle-max-hours)
GB_PER_HOUR = 1.35  # peak memory per hour of window at 1000 Hz with six channels (31.8 GB at 23.5 h)


@dataclass(frozen=True)
class MantleOptions:
    """The MANTLE settings a run uses, all recorded in the sidecar.

    The defaults are the LEMI-423 recipe of MANTLE's site runner and its
    shipped `ProcessingConfig` defaults: DPSS multitaper of 4096 samples at
    NW 3, a factor-4 cascade, the native level capped at 2 M samples, the
    robust remote-reference solve, a block jackknife of 8, the SNR gate on and
    prewhitening off. `n_levels` None takes `levels_for` on the window.
    `whiten` "diff" applies one first difference to every channel before
    `run_site`, which cancels in Z and removes the leakage of a red spectrum
    from the multitaper estimate. `max_hours` is the longest window
    `check_window` accepts.

    Attributes:
        nperseg (int): Multitaper segment length in samples.
        nw (float): DPSS time-bandwidth product.
        decim (int): Cascade decimation factor.
        n_levels (int | None): Cascade levels; None for `levels_for`.
        jackknife (int): Delete-one blocks of the jackknife.
        robust (bool): Bounded-influence solve rather than OLS.
        detrend (str): Whole-record detrend, "constant" or "linear".
        native_max_samples (int): Samples of the native level used.
        coil (bool): Deconvolve the archives' coil curve.
        snr_gate (bool): MANTLE's SNR-availability gate.
        min_segments (int): Fewest independent segments a band needs.
        whiten (str): "none" or "diff".
        max_hours (float): Longest window accepted, in hours.
    """

    nperseg: int = 4096
    nw: float = 3.0
    decim: int = 4
    n_levels: int | None = None
    jackknife: int = 8
    robust: bool = True
    detrend: str = "constant"
    native_max_samples: int = 2_000_000
    coil: bool = True
    snr_gate: bool = True
    min_segments: int = 3
    whiten: str = "none"
    max_hours: float = MAX_HOURS

    def __post_init__(self) -> None:
        if self.whiten not in WHITEN:
            raise ValueError(f"whiten {self.whiten!r} is not one of {WHITEN}")
        if not float(self.max_hours) > 0.0:
            raise ValueError(f"max_hours {self.max_hours!r} is not a positive number of hours")

    def to_dict(self) -> dict:
        """The options as a JSON-ready dict."""
        return asdict(self)


def levels_for(n_samples: int, nperseg: int = 4096, decim: int = 4, min_segments: int = 3,
               max_levels: int = MAX_LEVELS) -> int:
    """Return the cascade depth whose deepest level still holds `min_segments` segments.

    Level k runs on ``n_samples / decim**k`` samples; it can form
    ``n / nperseg`` independent segments, and the deepest level kept is the
    last with at least `min_segments` of them.

    Args:
        n_samples (int): Samples in the window at the native rate.
        nperseg (int): Segment length in samples.
        decim (int): Decimation factor between levels.
        min_segments (int): Fewest independent segments a level needs.
        max_levels (int): Upper bound on the depth.

    Returns:
        int: Number of levels, at least 1.
    """
    if n_samples < nperseg:
        return 1
    k_max = int(math.floor(math.log(n_samples / (min_segments * nperseg)) / math.log(decim)))
    return max(1, min(max_levels, k_max + 1))


def expected_peak_gb(hours: float) -> float:
    """Return the peak memory of a MANTLE run in GB: GB_PER_HOUR per hour of window (1000 Hz, six channels)."""
    return GB_PER_HOUR * float(hours)


def check_window(hours: float, max_hours: float = MAX_HOURS) -> None:
    """Refuse a window longer than `max_hours`; log the expected peak when the limit is above MAX_HOURS.

    Args:
        hours (float): Length of the window in hours.
        max_hours (float): Longest window accepted, in hours.

    Raises:
        ValueError: If `hours` exceeds `max_hours`.
    """
    if hours > max_hours:
        raise ValueError(f"the window is {hours:.1f} h; MANTLE holds the whole window in memory, so give "
                         f"process_rr.py a start and end at most {max_hours:g} h apart")
    if max_hours > MAX_HOURS:
        logger.warning(f"{ENGINE}: window limit {max_hours:g} h, above the default {MAX_HOURS:g} h: this "
                       f"{hours:.1f} h window needs about {expected_peak_gb(hours):.0f} GB at its peak "
                       f"({GB_PER_HOUR:g} GB per hour of window at 1000 Hz with six channels)")


def band_list(scheme: dict) -> list[tuple[float, float]]:
    """Flatten a `build_band_scheme` result into ``(lo_hz, hi_hz)`` bands, highest first."""
    bands = []
    for level in sorted(scheme["band_edges"]):
        for lo, hi in np.asarray(scheme["band_edges"][level], dtype=float):
            bands.append((float(lo), float(hi)))
    return sorted(bands, key=lambda b: -b[0])


class _PoolContext:
    """The cross-frequency jackknife covariance of a cascade run, indexed on the merged grid.

    MANTLE merges its cascade bands by concatenating them in band order and
    sorting by descending frequency with a stable sort; the same order is
    rebuilt here and checked against the result's grid, so each merged bin is
    attributed to the jackknife of the band that made it. The covariance is
    block-diagonal over the cascade bands (each band is jackknifed over its
    own segmentation), which leaves a band straddling a cascade seam with a
    variance that is still optimistic.
    """

    def __init__(self, result) -> None:
        bands, band_freq = result.bands, result.band_freq
        if not bands or not band_freq or any(b is None for b in bands):
            raise ValueError("the result carries no per-band jackknife: pooled variance is unavailable")
        f_cat = np.concatenate([np.asarray(f, dtype=float) for f in band_freq])
        bid = np.concatenate([np.full(len(f), b, dtype=int) for b, f in enumerate(band_freq)])
        lid = np.concatenate([np.arange(len(f)) for f in band_freq])
        order = np.argsort(-f_cat, kind="stable")
        merged = np.asarray(result.impedance.freqs, dtype=float)
        if f_cat[order].shape != merged.shape or not np.array_equal(f_cat[order], merged):
            raise AssertionError("the rebuilt merge order is not the result's own frequency grid")
        self.bands = list(bands)
        self.bid = bid[order]
        self.lid = lid[order]
        self.jidx = []
        for b, jk in enumerate(self.bands):
            jf = np.asarray(jk.impedance.freqs, dtype=float)
            rf = np.asarray(band_freq[b], dtype=float)
            if jf.shape == rf.shape and np.array_equal(jf, rf):
                self.jidx.append(np.arange(rf.size))
                continue
            pos = {float(v): k for k, v in enumerate(jf)}
            self.jidx.append(np.array([pos[float(v)] for v in rf], dtype=int))

    def band_var(self, members: np.ndarray) -> np.ndarray:
        """Return the (2, 2) total variance of the mean of `members` (indices into the merged grid)."""
        m = int(len(members))
        out = np.full((2, 2), np.nan)
        if m == 0:
            return out
        groups = [(b, members[self.bid[members] == b]) for b in np.unique(self.bid[members])]
        for o in range(2):
            for i in range(2):
                total = 0.0
                for b, sel in groups:
                    fi = self.jidx[b][self.lid[sel]]
                    sigma = self.bands[b].covariance(o, i, fi)
                    if not np.all(np.isfinite(sigma)):
                        total = float("nan")
                        break
                    total += float(np.real(sigma.sum())) / (m * m)
                out[o, i] = total
        return out


def band_pool(result, bands: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """Pool a MANTLE `MultibandResult` onto bands.

    Each band takes the plain complex mean of the finite, status-ok bins in
    ``[lo, hi)`` and the period ``1 / sqrt(lo * hi)``. The variance of the
    mean is the pooled jackknife form of `_PoolContext` when the result
    carries the per-band jackknives, else the mean per-bin variance over the
    member count. Bands holding no bin are left out.

    Args:
        result: `MultibandResult` of `run_site`.
        bands (list of tuple): ``(lo_hz, hi_hz)`` bands.

    Returns:
        tuple: ``(periods, z, var)``: periods (nb,) ascending, z (nb, 2, 2)
        complex, var (nb, 2, 2) total complex variance or None without a
        jackknife.
    """
    imp = result.impedance
    f = np.asarray(imp.freqs, dtype=float)
    z = np.asarray(imp.Z)
    status = np.asarray(imp.status) if imp.status is not None else np.zeros(f.size, dtype=np.int8)
    ok = np.isfinite(f) & (f > 0) & np.all(np.isfinite(z), axis=(0, 1)) & (status == 0)
    var = None if result.var is None else np.asarray(result.var, dtype=float)
    ctx = None
    if var is not None:
        try:
            ctx = _PoolContext(result)
        except (ValueError, AssertionError) as exc:
            logger.warning(f"pooled variance unavailable ({exc}); using the mean per-bin variance")
    periods, zz, vv = [], [], []
    for lo, hi in bands:
        members = np.flatnonzero(ok & (f >= lo) & (f < hi))
        if members.size == 0:
            continue
        periods.append(1.0 / math.sqrt(lo * hi))
        zz.append(z[:, :, members].mean(axis=2))
        if var is not None:
            vv.append(ctx.band_var(members) if ctx is not None else var[:, :, members].mean(axis=2) / members.size)
    if not periods:
        raise ValueError("no band holds a usable bin of the MANTLE grid")
    order = np.argsort(periods)
    p = np.asarray(periods)[order]
    zb = np.stack(zz)[order]
    vb = np.stack(vv)[order] if var is not None else None
    return p, zb, vb


def to_tf(periods: np.ndarray, z: np.ndarray, var: np.ndarray | None, *, station: str, remote: str,
          survey: str, latitude: float, longitude: float, elevation: float, sample_rate: float,
          lines: list[str] | None = None) -> TF:
    """Build the mt_metadata TF of a band-pooled impedance.

    The EDI's Z.VAR is the single-component variance, half the total complex
    variance `var` carries, so the error handed to the TF is
    ``sqrt(0.5 * var)``.

    Args:
        periods (np.ndarray): (nb,) periods in s.
        z (np.ndarray): (nb, 2, 2) impedance in mV/km/nT.
        var (np.ndarray | None): (nb, 2, 2) total complex variance.
        station (str): Local station id.
        remote (str): Remote station id.
        survey (str): Survey id.
        latitude (float): Station latitude in degrees.
        longitude (float): Station longitude in degrees.
        elevation (float): Station elevation in m.
        sample_rate (float): Sample rate of the record in Hz.
        lines (list of str, optional): Processing-parameter lines for the INFO block.

    Returns:
        TF: The transfer function.
    """
    tf = TF()
    tf.station_metadata.id = station
    tf.survey_metadata.id = survey
    tf.station_metadata.location.latitude = float(latitude)
    tf.station_metadata.location.longitude = float(longitude)
    tf.station_metadata.location.elevation = float(elevation)
    tf.station_metadata.orientation.reference_frame = "geomagnetic"
    tf.station_metadata.transfer_function.remote_references = [remote]
    tf.station_metadata.transfer_function.processing_parameters.extend(list(lines or []))
    try:
        run = tf.station_metadata.runs[0]
        run.sample_rate = float(sample_rate)
        run.channels_recorded_electric = ["ex", "ey"]
        run.channels_recorded_magnetic = ["hx", "hy"]
    except Exception as exc:  # the run block is descriptive only
        logger.debug(f"run metadata left at defaults: {exc}")
    tf.period = np.asarray(periods, dtype=float)
    tf.impedance = np.asarray(z)
    if var is not None:
        tf.impedance_error = np.sqrt(0.5 * np.asarray(var, dtype=float))
    return tf


def _window_of(reader, local_h5: Path, remote_h5: Path, start, end) -> tuple[float, float]:
    """The processing window as epoch seconds: the given bounds, or the archives' common span."""
    lo, hi = zip(*(reader.open_station(p).span for p in (local_h5, remote_h5)), strict=True)
    t0 = reader.to_epoch(start) if start is not None else max(lo)
    t1 = reader.to_epoch(end) if end is not None else min(hi)
    if t1 <= t0:
        raise ValueError(f"the window [{start}, {end}) leaves no overlap of the two archives")
    return float(t0), float(t1)


def process_pair(local_h5, station: str, remote_h5, remote: str, *, survey_name: str, latitude: float,
                 longitude: float, elevation: float, out_dir, stem: str, scheme: dict,
                 start=None, end=None, options: MantleOptions | None = None) -> tuple[TF, dict]:
    """Estimate a remote-referenced TF with MANTLE and write its products.

    Reads both archives over ``[start, end)`` UTC (the archives' common span
    without bounds), runs `run_site` and writes ``<stem>_fine.edi`` and
    ``<stem>.mantle_report.json`` (MANTLE's own writer and report), then
    pools the fine grid onto `scheme` for the TF returned.

    Args:
        local_h5 (Path): Processing archive of the local station.
        station (str): Local station id.
        remote_h5 (Path): Processing archive of the remote station.
        remote (str): Remote station id.
        survey_name (str): Survey id.
        latitude (float): Station latitude in degrees.
        longitude (float): Station longitude in degrees.
        elevation (float): Station elevation in m.
        out_dir (Path): Folder for the products.
        stem (str): Product stem.
        scheme (dict): `build_band_scheme` result.
        start: Window start, UTC.
        end: Window end, UTC.
        options (MantleOptions, optional): Engine settings.

    Returns:
        tuple: ``(tf, extras)``, the band-pooled TF and the sidecar keys of
        `sidecar_extras`.

    Raises:
        ValueError: If the window exceeds `options.max_hours` (`check_window`)
            or leaves no overlap.
    """
    reader = _mantle.module("io.mth5_reader")
    run = _mantle.module("processing.run")
    opts = options or MantleOptions()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    local_h5, remote_h5 = Path(local_h5), Path(remote_h5)

    t0, t1 = _window_of(reader, local_h5, remote_h5, start, end)
    hours = (t1 - t0) / 3600.0
    check_window(hours, opts.max_hours)
    started = time.perf_counter()
    data, local, remote_w = reader.assemble_rr(local_h5, remote_h5, t0, t1)
    fs = float(local.fs)
    n = int(local.n_samples)
    logger.info(f"{ENGINE}: {station} rr {remote}, {n} samples at {fs:g} Hz ({hours:.2f} h) from {local.start_iso}, "
                f"read in {time.perf_counter() - started:.1f} s")
    if opts.whiten == "diff":
        data = {k: np.diff(np.asarray(v, dtype=float)) for k, v in data.items()}
        n -= 1
        logger.info(f"{ENGINE}: first difference applied to every channel before the cascade")
    coil = reader.coil_response_of(local_h5, remote_h5) if opts.coil else None
    n_levels = opts.n_levels or levels_for(n, opts.nperseg, opts.decim, opts.min_segments)

    config = run.ProcessingConfig(
        site_id=station, fs=fs, lat=float(latitude), lon=float(longitude),
        elev=float(elevation) if np.isfinite(elevation) else 0.0,
        references=("Hxr", "Hyr"), robust=opts.robust, prewhiten=False, detrend=opts.detrend,
        nperseg=opts.nperseg, nw=opts.nw, n_levels=n_levels, decim=opts.decim,
        native_max_samples=opts.native_max_samples, jackknife=opts.jackknife,
        min_segments=opts.min_segments, snr_gate=opts.snr_gate,
    )
    info = [
        f"engine {ENGINE} {_mantle.version()} via crust.engine_mantle",
        f"window {local.start_iso} + {n / fs / 3600.0:.3f} h at {fs:g} Hz",
        f"local archive {local_h5.name}; remote archive {remote_h5.name} ({remote})",
        "channels read by io.mth5_reader: H = counts*K*0.001 nT, E = -counts*K/L mV/km (the archive's "
        "lemimt convention carries the sign on H instead; Z is the same)",
        f"coil response {'deconvolved from the archives fap table' if coil is not None else 'off'}",
        f"whiten {opts.whiten}; prewhiten False; n_levels {n_levels} for {n} samples",
    ]
    fine_edi = out_dir / f"{stem}_fine.edi"
    report = out_dir / f"{stem}.mantle_report.json"
    solve_started = time.perf_counter()
    res = run.run_site(data, config, coil=coil, edi_path=fine_edi, report_path=report,
                       remote_site=remote, info_lines=info)
    logger.info(f"{ENGINE}: cascade of {n_levels} levels solved in {time.perf_counter() - solve_started:.1f} s; "
                f"wrote {fine_edi}")
    logger.info(f"wrote {report}")
    del data

    periods, zb, vb = band_pool(res.result, band_list(scheme))
    imp = res.result.impedance
    lines = [f"mantle.version={_mantle.version()}", f"mantle.n_levels={n_levels}",
             f"mantle.fine_bins={int(np.isfinite(imp.freqs).sum())}", f"mantle.band_periods={periods.size}",
             f"mantle.whiten={opts.whiten}"]
    tf = to_tf(periods, zb, vb, station=station, remote=remote, survey=survey_name, latitude=latitude,
               longitude=longitude, elevation=elevation, sample_rate=fs, lines=lines)
    extras = sidecar_extras(config, opts, n_levels=n_levels, report=report, fine_edi=fine_edi,
                            n_samples=n, window=(local.start_iso, hours), coil=coil is not None,
                            report_obj=res.report)
    return tf, extras


def sidecar_extras(config, options: MantleOptions, *, n_levels: int, report, fine_edi, n_samples: int,
                   window: tuple[str, float], coil: bool, report_obj=None) -> dict:
    """The keys this engine adds to the run's sidecar.

    Args:
        config: MANTLE `ProcessingConfig` used.
        options (MantleOptions): The options.
        n_levels (int): Cascade levels used.
        report (Path): MANTLE's report JSON.
        fine_edi (Path): MANTLE's fine-grid EDI.
        n_samples (int): Samples per channel handed to the cascade.
        window (tuple): ``(start_iso, hours)`` of the window read.
        coil (bool): Whether a coil curve was deconvolved.
        report_obj: MANTLE's `SiteReport`, for the verdict word counts.

    Returns:
        dict: ``engine``, ``engine_version``, ``engine_config``,
        ``mantle_report`` and ``mantle_fine_edi``.
    """
    words: dict[str, int] = {}
    snr_gate_ran = None
    if report_obj is not None:
        for v in getattr(report_obj, "verdicts", []) or []:
            word = v.get("word") if isinstance(v, dict) else getattr(v, "word", None)
            if word:
                words[word] = words.get(word, 0) + 1
        snr_gate_ran = getattr(report_obj, "snr_gate_ran", None)
    return {
        "engine": ENGINE,
        "engine_version": _mantle.version(),
        "engine_config": {
            "processing_config": config.to_dict(),
            "options": options.to_dict(),
            "n_levels": int(n_levels),
            "n_samples": int(n_samples),
            "window_start": window[0],
            "window_hours": float(window[1]),
            "coil_deconvolved": bool(coil),
            "prewhiten": False,
            "verdict_words": words,
            "snr_gate_ran": snr_gate_ran,
        },
        "mantle_report": Path(report).name,
        "mantle_fine_edi": Path(fine_edi).name,
    }
