"""Synthetic (stacked) remote-reference stations.

Builds a virtual station whose hx/hy are the mean of several concurrent
sites' magnetic counts. Each member is read from `mtproc.ingest.processing_archive`
(the site's filtered variant, built on demand from its raw archive when it
declares filters in `<survey>/filters.yaml`, else the raw archive itself --
written by `scripts/ingest_site.py` or the GUI's "Build MTH5"), so the stack
takes each member exactly as processing sees it, and none of that is applied
again here. No calibration is applied or declared: the RR estimator is invariant to any
linear transform of the remote channels, so only coherence with the true
field matters. Sample grids must align exactly (GPS-locked 1 ms grids): every
member's run start must sit on the common grid to 1e-3 of a sample; this is
asserted, not assumed.

The members are streamed: every weighting and the member check read each
member's hx/hy in `WEIGHT_CHUNK_S` chunks (the last one partial) straight
from the archive's HDF5 datasets, and only the two output coils are held
whole (float64; 2 GB for 36 h at 1000 Hz). Sample positions are integer
arithmetic from each run's start; no time coordinate is ever built.

Two weightings (`build_synthetic_remote(weighting=...)`):

- ``"none"`` (the default, unchanged): each coil is the plain mean of its
  members' counts. One dead coil poisons it -- check the members first
  (`check_members`, `scripts/build_stack.py --check`) and leave dead ones out.
- ``"coherence"``: per member, per `WEIGHT_CHUNK_S` chunk, per coil, the
  weight is the band-averaged squared coherence of that member's coil with
  the mean of the *other* members' same coil over `WEIGHT_BAND_S`
  (`member_coherence`: the `mtproc.timefreq` cascade and band line, no
  spectral maths of its own); the weights are normalised per chunk to sum
  to one, a member under `WEIGHT_FLOOR` in a chunk is dropped from it and the
  rest renormalised (`coherence_weights`). Each member's median is removed
  first, or a weight change between chunks would step the members' DC
  offsets (tens of millions of counts) into the stack. The rule and the mean
  weights go into the run's comments, each coil's per-chunk weights into
  its channel's comments.

Leave-one-out needs at least three live coils to say *which* member is bad:
with two, each member's reference is the other one and coherence is
symmetric, so their weights come out equal whatever either records. The
absolute `WEIGHT_FLOOR` also assumes fewer than 1 / 0.05 = 20 members (with
more, an average member is already under it).
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5

from .ingest import processing_archive
from .survey import Survey
from .timefreq import _real_runs, band_from_levels, cascade, levels_plan

WEIGHTINGS = ("none", "coherence")
WEIGHT_CHUNK_S = 600.0
WEIGHT_BAND_S = (0.1, 10.0)
WEIGHT_FLOOR = 0.05
# the member check's bands: the two decades separately, then the weight band
CHECK_BANDS_S = ((0.1, 1.0), (1.0, 10.0), WEIGHT_BAND_S)
# how far (in samples) a member's run start may sit off the common grid
GRID_TOL = 1e-3
COILS = ("hx", "hy")


class _Span(NamedTuple):
    """The common span: first sample (ns since the epoch, UTC), sample count, rate."""

    t0: int
    n: int
    fs: float

    def iso(self, j: int) -> str:
        """Sample j's time as the stack's metadata has always written it."""
        return _iso(self.t0 + int(round(j * (1e9 / self.fs))))


class _Coil:
    """One member's coil on the common span, read from its HDF5 dataset on demand.

    ``coil[a:b]`` (and ``coil[a:b:step]``) is samples a..b of the span, read
    from the dataset at the member's own offset `i0`; nothing is held.
    """

    def __init__(self, data, i0: int, n: int):
        self.data, self.i0, self.size = data, int(i0), int(n)

    def __getitem__(self, sl: slice) -> np.ndarray:
        a, b, step = sl.indices(self.size)
        return self.data[self.i0 + a : self.i0 + b : step]


def _ns(t) -> int | None:
    """A time (string, Timestamp; naive = UTC) as ns since the epoch, UTC; None stays None."""
    if t is None:
        return None
    ts = pd.Timestamp(t)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)


def _iso(ns: int) -> str:
    """ISO UTC to the microsecond, as the stack's metadata and comments have always carried it."""
    return str(np.datetime_as_string(np.datetime64(int(ns), "ns"), unit="us")) + "+00:00"


def _text(comment) -> str:
    value = getattr(comment, "value", comment)
    return "" if value is None else str(value)


def _chunks(n: int, w: int) -> list[tuple[int, int]]:
    """(first, stop) sample pairs covering [0, n) in pieces of `w`, the last one partial."""
    return [(s, min(s + w, n)) for s in range(0, n, w)]


def _member_run(survey: Survey, site: str, lo: int | None, hi: int | None, stack: ExitStack) -> dict:
    """Open `site`'s processing archive read-only (closed by `stack`); pick its run overlapping [lo, hi) most.

    Returns {"run", "start" (ns), "n", "fs", "hx", "hy" (the h5py datasets)}.
    `processing_archive` resolves the path -- the site's filtered variant
    (built from its raw archive on demand, if it is missing or stale) when it
    declares filters, its raw archive otherwise -- so the member is always
    taken exactly as processing would see it, current by construction; the
    stack itself applies nothing further.
    """
    try:
        path = processing_archive(survey, site)
    except FileNotFoundError:
        raise ValueError(
            f"{site}: no MTH5 archive -- build it first (Build MTH5 on the "
            f"Time Series tab, or scripts/ingest_site.py <survey.yaml> {site})"
        ) from None
    m = MTH5()
    m.open_mth5(path, mode="r")
    stack.callback(m.close_mth5)
    station = m.get_station(site, survey=survey.name)
    runs = []
    for run_id, _, _ in _real_runs(station):
        run = station.get_run(run_id)
        if not set(COILS) <= set(run.groups_list):
            logger.warning(f"{site}: run {run_id} has no {'/'.join(COILS)} -- skipped")
            continue
        grid = {}
        for c in COILS:
            ch = run.get_channel(c)
            grid[c] = (_ns(str(ch.metadata.time_period.start)), float(ch.metadata.sample_rate),
                       int(ch.hdf5_dataset.shape[0]), ch.hdf5_dataset)
        if grid["hx"][:3] != grid["hy"][:3]:
            raise ValueError(f"{site} {run_id}: hx and hy do not share a sample grid "
                             f"(start ns, rate, samples: {grid['hx'][:3]} vs {grid['hy'][:3]})")
        start, fs, n, _ = grid["hx"]
        stop = start + n * 1e9 / fs  # one sample past the last
        overlap = min(stop, np.inf if hi is None else hi) - max(start, -np.inf if lo is None else lo)
        runs.append(dict(run=run_id, start=start, n=n, fs=fs, overlap=overlap, comment=_text(run.metadata.comments),
                         hx=grid["hx"][3], hy=grid["hy"][3]))
    if not runs:
        raise ValueError(f"{site}: no run with hx and hy in {path}")
    best = max(runs, key=lambda r: r["overlap"])
    if best["overlap"] <= 0:
        raise ValueError(f"{site}: no run in {path} overlaps the stack's window")
    if len(runs) > 1:
        n_in = sum(r["overlap"] > 0 for r in runs)
        logger.info(f"{site}: using run {best['run']} of {len(runs)} in {path.name} "
                    f"({n_in} overlap the window; {best['overlap'] / 3.6e12:.2f} h of it in this one)")
    declared = [s for s in (getattr(survey.site(site), "filters", None) or []) if s]
    recorded = "ingest filters (in order)" in best["comment"]
    if bool(declared) != recorded:
        logger.warning(
            f"{site}: filters.yaml declares {len(declared)} filter(s) but the archive's run "
            f"{best['run']} records {'some' if recorded else 'none'} -- the stack takes the "
            f"archive as it is; rebuild the archive if it is stale"
        )
    return best


def _per_comp(members) -> dict[str, list[str]]:
    per_comp = members if isinstance(members, dict) else {"hx": list(members), "hy": list(members)}
    return {c: list(v) for c, v in per_comp.items()}


def _open_members(survey: Survey, per_comp: dict, start, end, name: str, stack: ExitStack):
    """(sorted member list, {coil: {member: _Coil}} in `per_comp` order, _Span).

    Each member's run is the one overlapping [start, end) most; the common
    span is those runs' intersection with [start, end), on the grid of the
    latest-starting run. Every member's run start must sit on that grid to
    `GRID_TOL` of a sample and every rate must be the same, or it raises.
    """
    all_members = sorted(set(per_comp["hx"]) | set(per_comp["hy"]))
    lo, hi = _ns(start), _ns(end)
    runs = {m: _member_run(survey, m, lo, hi, stack) for m in all_members}
    fs = runs[all_members[0]]["fs"]
    if any(abs(r["fs"] - fs) > 1e-9 * fs for r in runs.values()):
        raise ValueError(f"{name}: members' sample rates differ: "
                         + ", ".join(f"{m} {r['fs']:g} Hz" for m, r in runs.items()))
    anchor = max(all_members, key=lambda m: runs[m]["start"])
    a0 = runs[anchor]["start"]
    # the first sample of the anchor's grid at or after `start`
    k0 = 0 if lo is None or lo <= a0 else int(np.ceil((lo - a0) / 1e9 * fs - GRID_TOL))
    offsets = {}
    for m in all_members:
        pos = (a0 - runs[m]["start"]) / 1e9 * fs + k0
        offsets[m] = int(round(pos))
        if abs(pos - offsets[m]) > GRID_TOL:
            raise ValueError(
                f"{m}: sample grid does not align with the stack (its run {runs[m]['run']} starts "
                f"{pos - offsets[m]:+.4f} samples off {anchor}'s grid) — GPS timing "
                f"assumption violated, investigate before stacking"
            )
    n = min(runs[m]["n"] - offsets[m] for m in all_members)
    if hi is not None:
        n = min(n, int(np.ceil((hi - a0) / 1e9 * fs - k0 - GRID_TOL)))
    if n <= 0:
        raise ValueError(f"{name}: members do not overlap in [{start}, {end})")
    span = _Span(a0 + int(round(k0 * (1e9 / fs))), n, fs)
    coils = {c: {m: _Coil(runs[m][c], offsets[m], n) for m in per_comp[c]} for c in COILS}
    logger.info(f"{name}: common span {span.iso(0)} .. {span.iso(n - 1)} ({n} samples, "
                f"{n / fs / 3600:.2f} h at {fs:g} Hz) from {len(all_members)} archives")
    return all_members, coils, span


def _median(a, n: int | None = None) -> float:
    """A member's DC offset: the median of an even subsample of its first `n` samples.

    Exact enough and far cheaper; on an archived coil the subsample is one
    strided read of the HDF5 dataset.
    """
    n = a.size if n is None else n
    step = max(1, n // 1_000_000)
    return float(np.median(a[0:n:step]))


def member_coherence(
    arrays: dict,
    sample_rate: float,
    bands=(WEIGHT_BAND_S,),
    chunk_s: float = WEIGHT_CHUNK_S,
) -> tuple[np.ndarray, dict[tuple[float, float], np.ndarray]]:
    """Each member's band-averaged squared coherence with the mean of the others, per chunk.

    `arrays` is one coil, {member: 1-D array or archived coil}, all on the
    same sample grid; each chunk is read from it on its own. Each member's
    median (over the whole span) is removed, the leave-one-out mean of the
    others is formed chunk by chunk, and each chunk's pair goes through
    `mtproc.timefreq.cascade` on the ladder the whole span plans
    (`levels_plan` with window = step = `chunk_s`, periods from the shortest
    band edge to the longest), which gives every level exactly one window,
    the chunk; each band's value is `band_from_levels`: the mean of the
    band's log-period bins on each level, averaged over the levels reaching
    the band. (Over 0.1-10 s at 1000 Hz that is levels 0, 1 and 2 -- 0.1-1,
    1-4 and 4-10 s -- weighted equally.) Level 0 is what a whole-span cascade
    gives; the decimated levels see the chunk's own edges rather than its
    neighbours' samples (the FIR's reach, about 200 input samples a side).

    Returns (the chunks' first sample indices, {band: gamma2[member, chunk]})
    with members in `arrays` order. Samples after the last whole chunk are in
    no chunk (the stack gives them the last chunk's weights).
    """
    members = list(arrays)
    if len(members) < 2:
        raise ValueError("leave-one-out coherence needs at least two members")
    n = min(a.size for a in arrays.values())
    fs = float(sample_rate)
    w = int(round(chunk_s * fs))
    n_chunks = n // w
    lo = min(b[0] for b in bands)
    hi = max(b[1] for b in bands)
    plan = levels_plan(fs, n / fs, win_s=chunk_s, step_s=chunk_s, pmin=lo, pmax=hi)
    if (
        not np.allclose(plan["window_s"], chunk_s)
        or not np.allclose(plan["step_s"], chunk_s)
        or plan["period_ceiling_s"].iloc[-1] < hi
    ):
        raise ValueError(
            f"a {chunk_s:g} s chunk cannot carry the {lo:g}-{hi:g} s ladder on this record:\n{plan}"
        )
    t_mid = np.array([w / 2.0 / fs])  # the chunk's one window centre, on every level
    offsets = {m: _median(arrays[m], n) for m in members}
    out = {tuple(b): np.full((len(members), n_chunks), np.nan) for b in bands}
    pair = ("member", "others")
    logger.info(f"coherence of {len(members)} members over {n_chunks} chunks of {chunk_s:g} s, "
                f"ladder levels {list(plan['level'])}")
    # the cascade logs its ladder on every call: once per member per chunk is noise
    logger.disable("mtproc.timefreq")
    try:
        for k in range(n_chunks):
            s, e = k * w, (k + 1) * w
            xs = {m: np.asarray(arrays[m][s:e], dtype="float64") - offsets[m] for m in members}
            total = np.zeros(w, dtype="float64")
            for m in members:
                total += xs[m]
            for i, m in enumerate(members):
                chans = {
                    "member": xs[m].astype("float32"),
                    "others": ((total - xs[m]) / (len(members) - 1)).astype("float32"),
                }
                coh, _, _ = cascade(chans, [], fs, plan, pair, (pair,))
                for b in out:
                    out[b][i, k] = band_from_levels(coh[pair], b[0], b[1], t_mid)[0]
    finally:
        logger.enable("mtproc.timefreq")
    return np.arange(n_chunks) * w, out


def coherence_weights(gamma2: np.ndarray, floor: float = WEIGHT_FLOOR) -> np.ndarray:
    """gamma2[member, chunk] -> weights[member, chunk], each chunk summing to one.

    Normalise each chunk's gamma2 to sum to one; a member whose normalised
    weight is under `floor` is dropped (weight 0) and the rest renormalised.
    A NaN gamma2 counts as 0. A chunk where every gamma2 is 0/NaN keeps equal
    weights, and one where every member would be dropped (possible only with
    more than 1/floor members) keeps its undropped weights -- both logged.
    """
    g = np.nan_to_num(np.clip(np.asarray(gamma2, dtype="float64"), 0.0, 1.0), nan=0.0)
    n_members = g.shape[0]
    s = g.sum(axis=0)
    empty = s <= 0
    w = np.where(empty, 1.0 / n_members, g / np.where(empty, 1.0, s))
    kept = np.where(w < floor, 0.0, w)
    s2 = kept.sum(axis=0)
    none_left = s2 <= 0
    w = np.where(none_left, w, kept / np.where(none_left, 1.0, s2))
    if empty.any():
        logger.warning(f"{int(empty.sum())} chunk(s) with no coherence at all: equal weights")
    if (none_left & ~empty).any():
        logger.warning(
            f"{int((none_left & ~empty).sum())} chunk(s) where every member is under "
            f"{floor}: kept undropped"
        )
    return w


def _mean_stack(arrays: dict, sample_rate: float) -> np.ndarray:
    """One coil's plain mean of its members' counts (float64), chunk by chunk."""
    n = min(a.size for a in arrays.values())
    acc_all = np.zeros(n, dtype="float64")
    for s, e in _chunks(n, int(round(WEIGHT_CHUNK_S * sample_rate))):
        acc = np.zeros(e - s, dtype="float64")
        for a in arrays.values():
            acc += np.asarray(a[s:e], dtype="float64")
        acc_all[s:e] = acc / len(arrays)
    return acc_all


def _coherence_stack(arrays: dict, sample_rate: float) -> tuple[np.ndarray, dict]:
    """One coil's coherence-weighted stack (medians removed) and its weight record.

    Two passes over the members: `member_coherence` for the weights, then the
    weighted sum chunk by chunk (the partial last chunk takes the last whole
    chunk's weights).
    """
    members = list(arrays)
    n = min(a.size for a in arrays.values())
    starts, bands = member_coherence(arrays, sample_rate, bands=CHECK_BANDS_S)
    gamma2 = bands[WEIGHT_BAND_S]
    weights = coherence_weights(gamma2)
    offsets = {m: _median(arrays[m], n) for m in members}
    last = len(starts) - 1
    acc = np.zeros(n, dtype="float64")
    for k, (s, e) in enumerate(_chunks(n, int(round(WEIGHT_CHUNK_S * sample_rate)))):
        kk = min(k, last)  # the tail rides with the last whole chunk
        for i, m in enumerate(members):
            if weights[i, kk] > 0:
                acc[s:e] += weights[i, kk] * (np.asarray(arrays[m][s:e], dtype="float64") - offsets[m])
    info = {"members": members, "chunk_starts": starts, "bands": bands,
            "gamma2": gamma2, "weights": weights}
    return acc, info


def _weights_comments(infos: dict, t0: str) -> tuple[str, dict[str, str]]:
    """(run comment: rule + mean weights, {coil: channel comment with per-chunk weights})."""
    lo, hi = WEIGHT_BAND_S
    n_chunks = len(next(iter(infos.values()))["chunk_starts"])
    summary = []
    for comp, info in infos.items():
        cells = [
            f"{m} {info['weights'][i].mean():.3f} ({int((info['weights'][i] == 0).sum())})"
            for i, m in enumerate(info["members"])
        ]
        summary.append(f"{comp}: " + ", ".join(cells))
    run = (
        f"coherence-weighted stack (mtproc.virtual, weighting=coherence). Rule: per member, "
        f"per {WEIGHT_CHUNK_S:g} s chunk, per coil, weight = band-averaged squared coherence "
        f"({lo:g}-{hi:g} s, mtproc.timefreq cascade) of the member's coil with the mean of the "
        f"other members' same coil; normalised per chunk to sum to one; a member under "
        f"{WEIGHT_FLOOR:g} in a chunk dropped from it and the rest renormalised; samples after "
        f"the last whole chunk take its weights; each member's median removed before stacking. "
        f"{n_chunks} chunks from {t0}. Mean weight per member (chunks dropped): "
        + "; ".join(summary)
        + ". Per-chunk weights (per mille) are in each channel's comments."
    )
    chans = {}
    for comp, info in infos.items():
        rows = [
            f"{m} " + " ".join(str(int(v)) for v in np.rint(info["weights"][i] * 1000))
            for i, m in enumerate(info["members"])
        ]
        chans[comp] = (
            f"per-chunk stack weights, per mille, {WEIGHT_CHUNK_S:g} s chunks from {t0}: "
            + "; ".join(rows)
        )
    return run, chans


def check_members(survey: Survey, members, start, end, name: str = "check") -> dict:
    """{coil: {"members", "chunk_starts", "bands": {band: gamma2[member, chunk]}}}; writes nothing.

    The member check before stacking: each member's coil against the plain
    mean of the other members' same coil, per `WEIGHT_CHUNK_S` chunk, in
    `CHECK_BANDS_S`, on the same common span `build_synthetic_remote` would
    stack, each member read from its archive exactly as processing sees it.
    A dead coil sits near 0 in every band.
    """
    per_comp = _per_comp(members)
    out = {}
    with ExitStack() as stack:
        _, coils, span = _open_members(survey, per_comp, start, end, name, stack)
        for comp in COILS:
            starts, bands = member_coherence(coils[comp], span.fs, bands=CHECK_BANDS_S)
            out[comp] = {"members": list(per_comp[comp]), "chunk_starts": starts, "bands": bands}
    return out


def build_synthetic_remote(
    survey: Survey,
    members,
    start,
    end,
    name: str = "SYN01",
    out_path: Path | None = None,
    overwrite: bool = False,
    weighting: str = "none",
    weights_out: dict | None = None,
) -> Path:
    """Stack members' archived hx/hy counts into a virtual station MTH5.

    Each member is read from ``<workspace>/mth5/<member>.h5`` (a member
    without one raises: build it first), taking the run that overlaps
    [start, end) most, exactly as processing sees it -- the declared filters
    were applied at ingest and are not applied again. The common span is
    those runs' intersection with [start, end), streamed in
    `WEIGHT_CHUNK_S` chunks.

    `members` is a list of sites used for both coils, or a dict
    ``{"hx": [...], "hy": [...]}`` with a member list per coil — the
    coherence-selected stack: a site whose hy is dead can still lend its hx
    (Burra01), and vice versa (Burra37). With ``weighting="none"`` (the
    default) each coil is the plain mean of its members over the common span;
    with ``"coherence"`` it is the chunk-wise coherence-weighted sum the
    module docstring describes. `weights_out`, when a dict is given, receives
    ``{coil: {"members", "chunk_starts", "bands", "gamma2", "weights"}}``
    from a coherence-weighted build (nothing from an unweighted one or a
    reused archive).
    """
    if weighting not in WEIGHTINGS:
        raise ValueError(f"weighting {weighting!r} is not one of {WEIGHTINGS}")
    out_path = Path(out_path) if out_path else survey.workspace / "mth5" / f"{name}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        if not overwrite:
            logger.info(f"{out_path} exists — reusing (overwrite=False)")
            return out_path
        out_path.unlink()

    per_comp = _per_comp(members)
    total, infos = {}, {}
    with ExitStack() as stack:
        all_members, coils, span = _open_members(survey, per_comp, start, end, name, stack)
        for comp in COILS:
            if weighting == "none":
                total[comp] = _mean_stack(coils[comp], span.fs)
            else:
                total[comp], infos[comp] = _coherence_stack(coils[comp], span.fs)
            how = "mean" if weighting == "none" else "coherence-weighted sum"
            logger.info(f"{name}: {comp} = {how} of {per_comp[comp]} ({span.n} samples)")
    members = all_members
    if weights_out is not None:
        weights_out.update(infos)
    t0_iso, t1_iso = span.iso(0), span.iso(span.n - 1)
    run_comment, chan_comments = _weights_comments(infos, t0_iso) if infos else (None, {})

    # centroid location for metadata
    lats = [survey.site(m).latitude for m in members if survey.site(m).latitude]
    lons = [survey.site(m).longitude for m in members if survey.site(m).longitude]

    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = m.add_station(name, survey=survey.name)
        if lats and lons:
            station_group.metadata.location.latitude = float(np.mean(lats))
            station_group.metadata.location.longitude = float(np.mean(lons))
        if weighting == "none":
            station_group.metadata.comments = (
                f"synthetic remote: mean of raw hx/hy counts from {', '.join(members)}; "
                f"uncalibrated by design (RR estimator is calibration-invariant)"
            )
        else:
            station_group.metadata.comments = (
                f"synthetic remote: coherence-weighted stack of raw hx/hy counts (medians "
                f"removed) from {', '.join(members)}; uncalibrated by design (RR estimator "
                f"is calibration-invariant); weights in the run and channel comments"
            )
        station_group.write_metadata()

        run_group = station_group.add_run("sr1000_0001")
        for comp in COILS:
            # the virtual station carries no filters (the channel is written
            # without any): RR is calibration-invariant
            ch = run_group.add_channel(
                comp,
                "magnetic",
                total[comp].astype("float32"),
                channel_dtype="float32",
            )
            ch.metadata.component = comp
            ch.metadata.sample_rate = span.fs
            ch.metadata.time_period.start = t0_iso
            ch.metadata.time_period.end = t1_iso
            ch.metadata.units = "digital counts"
            ch.metadata.measurement_azimuth = 0.0 if comp == "hx" else 90.0
            if comp in chan_comments:
                # the Comment's value: a plain string would be parsed on "|"
                ch.metadata.comments.value = chan_comments[comp]
            ch.write_metadata()
            total[comp] = None  # release the float64 coil once it is written
        run_group.metadata.sample_rate = span.fs
        run_group.metadata.time_period.start = t0_iso
        run_group.metadata.time_period.end = t1_iso
        if run_comment:
            run_group.metadata.comments.value = run_comment
        run_group.write_metadata()
        station_group.metadata.time_period.start = run_group.metadata.time_period.start
        station_group.metadata.time_period.end = run_group.metadata.time_period.end
        station_group.write_metadata()
    finally:
        m.close_mth5()
    logger.info(f"{name}: wrote {out_path}")
    return out_path
