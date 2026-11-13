# -*- coding: utf-8 -*-
"""
Member check and stack preview on a bounded span

The Stacks tab checks a recipe's members on the loaded window before the
recipe is saved or built: each member's squared coherence with the mean of
the other members (`mt_workbench.virtual.member_coherence`, the
`mt_workbench.timefreq` cascade), each member's polarity against the
others (`mt_workbench.intersite.polarity_band` through `polarity_screen`
and `polarity_summary`), and a preview of the stack's band power beside
the members'. This module holds that maths and no Qt;
`mt_workbench.gui.stack_check.MemberCheck` reads the members and runs it in
a thread.

The span is bounded (`check_span`): at most `MAX_CHECK_SAMPLES` samples per
member channel at the recipe's rate, one hour at 1000 Hz, a whole 24 h tree
window at 1 Hz. The bands, the chunk and the polarity periods scale with
the rate (`check_plan`), so a 1 Hz recipe is checked where 1 Hz data carry
signal.

One gap rule holds on every path, keeping gap samples out of every value:

- coherence runs on the arrays as `mt_workbench.gui.segment.load_segment`
  gives them (zero in the gaps), and a chunk touching any member's gap is
  marked unusable and left out of the summaries;
- the polarity and the preview run on band spectra of a copy with NaN at
  every member's gaps, so `intersite.band_spectra` drops each window that
  touches a gap;
- the time-domain preview stacks the arrays as they are
  (`virtual.stack_arrays`), then puts NaN at the gaps in a copy of the
  stack and the members before their band spectra.

A member is flagged dead when its median squared coherence over the full
band, over the usable chunks, is under `DEAD_GAMMA2`, and reversed when its
median polarity correlation over the screened bands is negative
(`polarity_summary`'s rule) and it is not dead: a dead member's correlation
with the others is noise around zero, and its sign says nothing.

The check is a QC view of the loaded window: it writes no file and
builds no filtered variant.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.signal import get_window

from mt_workbench import intersite, virtual
from mt_workbench.bands import build_band_scheme

MAX_CHECK_SAMPLES = 3_600_000  # per member channel: 1 h at 1000 Hz, 41 days at 1 Hz
MAX_CHECK_MEMBERS = 16  # 16 members, two channels, 3.6 M float32 each: 461 MB held
DEAD_GAMMA2 = 0.1  # a choice: full-band median gamma2 under it flags a member dead
OVER_CAP = f"not checked: over {MAX_CHECK_MEMBERS} members"
ENGINES = ("band", "time")
NOTE_FEW = "fewer than two members: nothing to compare"
# the preview's band layout: periods per decade as the survey default, the shortest
# period at four samples (the band scheme's own cap at a quarter of the rate)
PREVIEW_PERIODS_PER_DECADE = 10.0


def _sig(x: float) -> float:
    """Round to 12 significant digits, so a scaled band edge reads 10.0 rather than 10.000000000000002."""
    return float(f"{float(x):.12g}")


def check_plan(sample_rate: float, span_s: float | None = None) -> dict:
    """Return the check's bands, chunk and polarity periods at a sample rate.

    With ``k = max(1, 100 / sample_rate)``, the bands are
    `virtual.CHECK_BANDS_S` times k, the chunk is `virtual.WEIGHT_CHUNK_S`
    times k and the polarity periods `intersite.POLARITY_PERIODS` times k.
    At 100 Hz and above that is 0.1-1, 1-10 and 0.1-10 s on 600 s chunks
    and 1-100 s; at 1 Hz 10-100, 100-1000 and 10-1000 s on 60000 s chunks
    and 100-10000 s, since 0.1 s cannot be read at 1 Hz.

    The ladder planner (`timefreq.levels_plan`) wants three windows per
    level, so `virtual.member_coherence` refuses a span shorter than three
    chunks: a 24 h tree window at 1 Hz holds 1.44 chunks of 60000 s
    [measured: "no usable level"]. With `span_s`, the chunk is shortened to
    a whole second at most a third of the span. It still has to carry the
    ladder, which takes 80 s at 1000 Hz (0.1-10 s) and 4610 s at 1 Hz
    (10-1000 s) [measured]; `member_coherence` refuses a shorter one and the
    check's note says so.

    Args:
        sample_rate (float): The members' sample rate, Hz.
        span_s (float, optional): The span's length, s.

    Returns:
        dict: ``factor`` (k), ``bands`` (tuple of (pmin, pmax) s, the full
        band last), ``full_band``, ``chunk_s``, ``polarity_periods`` and
        ``scheme`` (keyword arguments of `bands.build_band_scheme` for the
        polarity and the preview).

    Raises:
        ValueError: For a sample rate that is not positive.
    """
    fs = float(sample_rate)
    if not fs > 0:
        raise ValueError(f"sample rate {sample_rate}: must be positive")
    k = max(1.0, 100.0 / fs)
    chunk_s = _sig(virtual.WEIGHT_CHUNK_S * k)
    if span_s is not None and 3 * chunk_s > float(span_s):
        chunk_s = float(max(1, int(float(span_s) / 3)))
    bands = tuple((_sig(lo * k), _sig(hi * k)) for lo, hi in virtual.CHECK_BANDS_S)
    periods = (_sig(intersite.POLARITY_PERIODS[0] * k), _sig(intersite.POLARITY_PERIODS[1] * k))
    return {
        "factor": k,
        "bands": bands,
        "full_band": bands[-1],  # CHECK_BANDS_S ends with WEIGHT_BAND_S
        "chunk_s": chunk_s,
        "polarity_periods": periods,
        "scheme": {"min_period": 4.0 / fs, "max_period": max(periods[1], bands[-1][1]),
                   "periods_per_decade": PREVIEW_PERIODS_PER_DECADE},
    }


def _utc(t) -> pd.Timestamp:
    """Return `t` as a UTC Timestamp; a naive time is taken as UTC."""
    ts = pd.Timestamp(t)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def check_span(t0, end, sample_rate: float) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the span the check reads: from `t0` for at most `MAX_CHECK_SAMPLES` samples.

    Args:
        t0: The loaded segment's first sample, UTC (naive taken as UTC).
        end: The loaded segment's end, UTC.
        sample_rate (float): The recipe's rate, the rate the members are read at, Hz.

    Returns:
        tuple: ``(t0, min(end, t0 + MAX_CHECK_SAMPLES / sample_rate s))`` as UTC Timestamps.

    Raises:
        ValueError: For a sample rate that is not positive, or an end not after t0.
    """
    fs = float(sample_rate)
    if not fs > 0:
        raise ValueError(f"sample rate {sample_rate}: must be positive")
    t0, end = _utc(t0), _utc(end)
    if not end > t0:
        raise ValueError(f"span end {end} is not after its start {t0}")
    return t0, min(end, t0 + pd.Timedelta(seconds=MAX_CHECK_SAMPLES / fs))


@dataclass
class CheckResult:
    """The member check and the stack preview on one span.

    Attributes:
        span (tuple | None): (start, end) UTC Timestamps; set by the caller,
            since `compute_check` takes arrays only.
        sample_rate (float): Hz.
        roles (tuple): The channels checked, e.g. ("hx", "hy").
        members (list): Sites checked, in order.
        skipped (list): (site, reason) for sites not checked.
        chunk_starts (np.ndarray): Each coherence chunk's first sample.
        coherence (dict): {role: {band: gamma2[member, chunk]}}.
        usable (dict): {role: bool[chunk]}: False for a chunk touching a gap.
        polarity (dict): {role: correlation[member]}: NaN where none.
        flags (dict): {(site, role): list of "dead", "reversed"}, every pair.
        preview (dict): {role: {"periods" [band], "members" [member, band],
            "stack" [band]}}: band powers, the median over windows of the
            mean over harmonics of |X|^2, taken to a one-sided PSD on the
            band's level (units^2/Hz, uncalibrated: gains only) so that the
            levels join up.
        weights (dict | None): {role: weights[member, chunk]} for the
            coherence-weighted time stack, else None.
        engine (str): "band" or "time".
        stack (str): "mean" or "median".
        weighting (str): "none" or "coherence".
        note (str): What could not be computed and why; "" when all was.
    """

    span: tuple | None
    sample_rate: float
    roles: tuple
    members: list
    skipped: list
    chunk_starts: np.ndarray
    coherence: dict
    usable: dict
    polarity: dict
    flags: dict
    preview: dict
    weights: dict | None
    engine: str
    stack: str
    weighting: str
    note: str = ""


def _gap_mask(n: int, gaps) -> np.ndarray:
    """Return a boolean [n] mask, True inside any of the [a, b) gaps."""
    mask = np.zeros(n, dtype=bool)
    for a, b in gaps:
        mask[max(0, int(a)):min(n, int(b))] = True
    return mask


def _median_power(X: np.ndarray) -> float:
    """Return the median over windows of the mean over harmonics of |X|^2, over finite windows; NaN with none."""
    bp = np.mean(np.abs(X) ** 2, axis=-1, dtype=np.float64)
    bp = bp[np.isfinite(bp)]
    return float(np.median(bp)) if bp.size else float("nan")


def _coherence(arrays: dict, members: list, role: str, fs: float, plan: dict, gap_any: np.ndarray, notes: list):
    """Return (chunk_starts, {band: gamma2}, usable) for one role; empty when the span cannot carry a chunk."""
    try:
        starts, coh = virtual.member_coherence({m: arrays[m][role] for m in members}, fs,
                                               bands=plan["bands"], chunk_s=plan["chunk_s"])
    except ValueError as exc:
        notes.append(f"{role} coherence: {exc}".splitlines()[0])
        return np.zeros(0, dtype=int), {}, np.zeros(0, dtype=bool)
    w = int(round(plan["chunk_s"] * fs))
    usable = np.array([not gap_any[s:s + w].any() for s in starts], dtype=bool)
    return np.asarray(starts), {tuple(b): np.asarray(g, dtype=float) for b, g in coh.items()}, usable


def _spectra_pass(channels: dict, members: list, role: str, fs: float, plan: dict, engine: str, stack: str,
                  reject_factor: float, min_members: int, notes: list) -> tuple[np.ndarray, dict]:
    """Run band_spectra once over NaN-gapped copies; return (polarity[member], preview) for one role.

    `channels` maps "m<i>" (and "stack" for the time engine, when it could
    be formed) to a float32 copy with NaN at the gaps; band_spectra
    consumes it.
    """
    record: list = []
    keyed = [(site, {role: f"m{i}"}) for i, site in enumerate(members)]
    periods, member_power, stack_power = [], [], []
    try:
        scheme = build_band_scheme(fs, **plan["scheme"])
        bands = intersite.band_spectra(channels, fs, scheme)
        for band in intersite.polarity_screen(bands, keyed, (role,), periods=plan["polarity_periods"],
                                              reject_factor=reject_factor, record=record):
            X = np.stack([band.spectra[f"m{i}"] for i in range(len(members))])
            if engine == "band":
                res = intersite.stack_band(X, reject_factor, min_members, method=stack)
                scales = res["scale"][np.isfinite(res["scale"])]
                rms2 = float(np.mean(scales ** 2)) if scales.size else float("nan")
                s_power = _median_power(res["stack"]) * rms2
            elif "stack" in band.spectra:
                s_power = _median_power(band.spectra["stack"])
            else:  # the time stack failed (noted): the members still give the polarity
                s_power = float("nan")
            # |X|^2 to a one-sided PSD on the band's level, so the bands of the levels join up
            to_psd = _psd_factor(scheme, band.level, fs)
            periods.append(band.period)
            member_power.append([_median_power(X[i]) * to_psd for i in range(len(members))])
            stack_power.append(s_power * to_psd)
    except ValueError as exc:
        notes.append(f"{role} spectra: {exc}".splitlines()[0])
    summary = intersite.polarity_summary(record, members, (role,))
    polarity = np.array([np.nan if s["correlation"] is None else s["correlation"] for s in summary], dtype=float)
    preview = {"periods": np.asarray(periods, dtype=float),
               "members": np.asarray(member_power, dtype=float).reshape(len(periods), len(members)).T,
               "stack": np.asarray(stack_power, dtype=float)}
    return polarity, preview


def _psd_factor(scheme: dict, level: int, fs: float) -> float:
    """Return the factor taking |X|^2 of a band on `level` to a one-sided PSD, 2 / (fs_level sum(taper^2))."""
    fs_level = fs / float(np.prod([int(f) for f in scheme["decimation_factors"][:level + 1]]))
    taper = get_window("hann", int(scheme["num_samples_window"][level]))
    return 2.0 / (fs_level * float(np.sum(taper ** 2)))


def band_summary(values: np.ndarray, usable: np.ndarray) -> tuple[float, float] | None:
    """Return (median, 10th percentile) of one member's gamma2 over the usable chunks, or None without one.

    A chunk with no value (NaN: a flat coil's 0/0) counts as 0, since a
    member that carries nothing has no coherence with the others.
    """
    v = np.nan_to_num(np.asarray(values, dtype=float)[np.asarray(usable, dtype=bool)], nan=0.0)
    if not v.size:
        return None
    return float(np.median(v)), float(np.percentile(v, 10))


def compute_check(arrays: dict, gaps: dict, sample_rate: float, roles, engine: str, stack: str = "mean",
                  weighting: str = "none", reject_factor: float = intersite.STACK_REJECT_FACTOR,
                  min_members: int = intersite.STACK_MIN_MEMBERS) -> CheckResult:
    """Check the members and preview their stack on one span.

    Args:
        arrays (dict): {site: {role: float32 [n]}} as `load_segment` gives
            them (offset removed, zero in the gaps), every array of one
            length on one grid. Not modified. The first
            `MAX_CHECK_MEMBERS` sites are checked, the rest skipped.
        gaps (dict): {site: [(i0, i1)]}: the samples no run covers.
        sample_rate (float): Hz.
        roles (tuple): The channels to check, e.g. ("hx", "hy").
        engine (str): "band" (`intersite.stack_band`) or "time" (`virtual.stack_arrays`).
        stack (str): The band stack's method, "mean" or "median"; the time
            engine takes "mean" only.
        weighting (str): The time stack's weighting, "none" or "coherence";
            the band engine takes "none" (or None) only.
        reject_factor (float): `stack_band`'s rejection threshold.
        min_members (int): Kept members a band-stack window needs.

    The coherence chunk is `check_plan`'s for a span this long: a third of
    the span when it holds fewer than three. A step that cannot run on the
    span (coherence on a span too short for the ladder, a coherence-weighted
    time stack on under 1800 s, the 600 s chunks `virtual` fixes) is left
    empty and named in `note`.

    Returns:
        CheckResult: With `span` None; with fewer than two members a result
        whose `note` says so and whose fields are empty.

    Raises:
        ValueError: For an unknown engine, stack or weighting, a pairing the
            engine does not take, a role missing from a member, or arrays of
            unequal length.
    """
    weighting = "none" if weighting is None else str(weighting)
    if engine not in ENGINES:
        raise ValueError(f"engine {engine!r}: one of {ENGINES}")
    if weighting not in virtual.WEIGHTINGS:
        raise ValueError(f"weighting {weighting!r}: one of {virtual.WEIGHTINGS}")
    if engine == "band" and weighting != "none":
        raise ValueError(f"the band engine takes no weighting, got {weighting!r}")
    if engine == "time" and stack != "mean":
        raise ValueError(f"the time engine stacks the mean only, got {stack!r}")
    if stack not in intersite.STACK_METHODS:
        raise ValueError(f"stack {stack!r}: one of {intersite.STACK_METHODS}")
    roles = tuple(roles)
    fs = float(sample_rate)
    sites = list(arrays)
    members, skipped = sites[:MAX_CHECK_MEMBERS], [(s, OVER_CAP) for s in sites[MAX_CHECK_MEMBERS:]]
    lengths = set()
    for site in members:
        for role in roles:
            if role not in arrays[site]:
                raise ValueError(f"{site} has no {role}")
            lengths.add(int(np.asarray(arrays[site][role]).size))
    if len(lengths) > 1:
        raise ValueError(f"the members' arrays differ in length: {sorted(lengths)}")
    empty = CheckResult(None, fs, roles, members, skipped, np.zeros(0, dtype=int), {}, {}, {}, {}, {}, None,
                        engine, stack, weighting, NOTE_FEW)
    if len(members) < 2:
        return empty
    n = lengths.pop()
    plan = check_plan(fs, span_s=n / fs)
    gap_any = _gap_mask(n, [g for site in members for g in gaps.get(site, ())])
    notes: list[str] = []
    chunk_starts = np.zeros(0, dtype=int)
    coherence, usable, polarity, preview = {}, {}, {}, {}
    weights = {} if engine == "time" and weighting == "coherence" else None
    for role in roles:
        starts, coh, use = _coherence(arrays, members, role, fs, plan, gap_any, notes)
        if starts.size:
            chunk_starts = starts
        coherence[role], usable[role] = coh, use
        channels = {}
        if engine == "time":
            try:
                summed, info = virtual.stack_arrays({m: arrays[m][role] for m in members}, fs, weighting=weighting)
            except ValueError as exc:
                notes.append(f"{role} time stack: {exc}".splitlines()[0])
                summed, info = None, {}
            if summed is not None:
                channels["stack"] = np.asarray(summed, dtype=np.float32).copy()
            if weights is not None and "weights" in info:
                weights[role] = np.asarray(info["weights"], dtype=float)
        for i, m in enumerate(members):
            channels[f"m{i}"] = np.array(arrays[m][role], dtype=np.float32, copy=True)
        for key in channels:
            channels[key][gap_any] = np.nan
        pol, prev = _spectra_pass(channels, members, role, fs, plan, engine, stack, reject_factor, min_members,
                                  notes)
        del channels
        polarity[role], preview[role] = pol, prev
    flags = {}
    full = plan["full_band"]
    for role in roles:
        for i, site in enumerate(members):
            marks = []
            values = coherence[role].get(full)
            summary = band_summary(values[i], usable[role]) if values is not None else None
            dead = summary is not None and summary[0] < DEAD_GAMMA2
            if dead:
                marks.append("dead")
            corr = polarity[role][i]
            if not dead and np.isfinite(corr) and corr < 0:
                marks.append("reversed")
            flags[(site, role)] = marks
    return CheckResult(None, fs, roles, members, skipped, chunk_starts, coherence, usable, polarity, flags,
                       preview, weights, engine, stack, weighting, "; ".join(notes))
