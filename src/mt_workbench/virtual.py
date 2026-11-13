# -*- coding: utf-8 -*-
"""
Synthetic (stacked) remote-reference stations

`build_synthetic_remote` writes a virtual station whose hx and hy are the
mean of several concurrent sites' magnetic counts. Each member is read
through `mt_workbench.ingest.processing_archive`: the site's filtered variant,
built on demand from its raw archive when the site declares filters in
`<survey>/filters.yaml`, else the raw archive written by
`scripts/ingest_site.py` or the GUI "Build MTH5" button. The stack takes
each member as processing sees it and applies no further filters. Sample
grids must align exactly (GPS-locked 1 ms grids): every member's run start
must sit on the common grid to within 1e-3 of a sample, and this is checked.

Calibration. The stack's channels carry the members' common filter chain
(`calibration_plan`). Per coil, the first listed member is the reference,
and every other member's total response (the product of its applied
filters' complex responses, which is what processing divides the channel's
Fourier coefficients by) is compared with the reference's on
`RESPONSE_GRID_N` frequencies from `RESPONSE_GRID_HZ` to the Nyquist
frequency. A member whose ratio to the reference is a real constant to
`RESPONSE_RTOL` (the same coil model and logger, or chains that differ by
coefficient gains only) is scaled by the inverse of that constant before
the median, the coherence and the sum, so every member is on the
reference's scale; a member whose ratio varies with frequency (another coil
model or response table) refuses the build, since no one chain describes
the mixture. The stack's channel is written with the reference's filters
(copied into the archive's Filters group), applied flags, stages and units,
so processing calibrates the stack as it does a member, and a transfer
function estimated against it carries errors in physical units. The
remote-reference estimate is invariant to the remote's calibration; its
error is not: aurora's inverse signal covariance goes as the inverse square
of the remote's gain (upstream 111 and 116), which is why an
uncalibrated stack gave errors 1e-5 of a calibrated partner's. Members that
carry no chain at all give a stack written as before (digital counts, no
filters), with a warning. A member with no chain beside members with one
(an INTERMAGNET observatory archive in nanoTesla beside EDL sites in
microVolt) is taken as
an identity chain when its channel's units are those the reference chain
calibrates to (the units_in of the reference's first applied filter,
`_unit_key` spelling-blind: nT and nanoTesla agree): its total response is
1, so its ratio to the reference is 1 / R_ref, and when that is a real
constant (a chain of coefficients) the member is scaled by R_ref onto the
reference's scale like a member of another gain; the reference is then the
first listed member with a chain. The run comment's calibration line, the
station comment and `calibration_out` (``identity``) name it ("member CNB:
no filter chain, samples in nanoTesla taken as calibrated"). A chain-less
member in other units (or none) is refused, and so is one beside a
reference chain whose response varies with frequency (a coil table), since
no single chain could then describe the mixture.

The members are streamed: every weighting and the member check read each
member's hx and hy in `WEIGHT_CHUNK_S` chunks (the last one partial) from
the archive's HDF5 datasets, and only the two output coils are held whole
(float64; 2 GB for 36 h at 1000 Hz). Sample positions are computed as
integers from each run's start, without a time coordinate.

Pieces. By default each member gives the run that overlaps the window
most, so a member that restarted or has a gap cuts the stack to one of its
runs. `build_synthetic_remote(min_piece_h=H)` builds per piece instead:
the window is split into the stretches in which every member is inside one
of its runs (`stack_pieces`); each stretch of at least H hours becomes one
run of the stack, on its own common grid, and the shorter ones are left
out and logged. scripts/campaign.py builds its stage 2 stacks this way.
The stack's runs are named after the members' rate (sr10_0001,
sr10_0002 at 10 Hz; sr1000_0001 at 1000 Hz).

Two weightings (`build_synthetic_remote(weighting=...)`):

- ``"none"`` (the default): each coil is the plain mean of its members'
  counts. One dead coil corrupts it, so check the members first
  (`check_members`, `scripts/build_stack.py --check`) and leave dead ones
  out.
- ``"coherence"``: per member, per `WEIGHT_CHUNK_S` chunk and per coil, the
  weight is the band-averaged squared coherence of that member's coil with
  the mean of the other members' same coil over `WEIGHT_BAND_S`
  (`member_coherence`, using the `mt_workbench.timefreq` cascade and band
  averaging). The weights are normalised per chunk to sum to one; a member
  under `WEIGHT_FLOOR` in a chunk is dropped from it and the rest
  renormalised (`coherence_weights`). Each member's median is removed
  first, since otherwise a weight change between chunks would step the
  members' DC offsets (tens of millions of counts) into the stack. The rule
  and the mean weights are written to the run comments, and each coil's
  per-chunk weights to its channel comments.

Leave-one-out needs at least three live coils to identify a bad member:
with two, each member's reference is the other and coherence is symmetric,
so both get equal weights whatever either records. The absolute
`WEIGHT_FLOOR` also assumes fewer than 1 / 0.05 = 20 members; with more, an
average member is already under it.

`stack_arrays` is the one entry to both weightings for arrays already
read, so the archive and the GUI's member check (`mt_workbench.stackcheck`)
stack by the same code. There is no sample-wise median: it would scale
the members by their RMS, which their longest periods set, so outside
that band it would carry the middle member's own noise where the mean
averages the members' noise down (0.87 of one member's error power
against the mean's 0.19 on a synthetic test of the Stacks tab's design).
The band stack's median (`mt_workbench.intersite.stack_band`) scales each
band on its own and has no such fault.

Provenance. A stack built from a recipe of stacks.yaml
(`mt_workbench.stacks`, scripts/build_stack.py --recipe) is given a
``provenance`` dict: the recipe's name, hash, text and rule, the resolved
members, and each member's processing-archive identity
(`mt_workbench.ingest.archive_identity`). The station comment then ends
in ``; recipe=<name> recipe_hash=<hash>``, and the run comment ends in a
line ``provenance: <json>``, which `recorded_provenance` reads back, so a
later build can tell whether the archive still answers its recipe and
members. mt_metadata splits a comment on "|" into time, author and value,
so every "|" of the JSON is written as its JSON escape. A build without
provenance writes what it wrote before.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from pathlib import Path
from typing import NamedTuple

import h5py
import numpy as np
import pandas as pd
from loguru import logger
from mth5.helpers import validate_name
from mth5.mth5 import MTH5

from .ingest import processing_archive
from .survey import Survey
from .timefreq import _real_runs, band_from_levels, cascade, levels_plan

WEIGHTINGS = ("none", "coherence")
WEIGHT_CHUNK_S = 600.0
WEIGHT_BAND_S = (0.1, 10.0)
WEIGHT_FLOOR = 0.05
# bands of the member check: the two decades separately, then the weight band
CHECK_BANDS_S = ((0.1, 1.0), (1.0, 10.0), WEIGHT_BAND_S)
# largest offset, in samples, of a member's run start from the common grid
GRID_TOL = 1e-3
COILS = ("hx", "hy")
# the members' responses are compared on RESPONSE_GRID_N log-spaced frequencies from RESPONSE_GRID_HZ to Nyquist;
# a ratio of responses that is a constant to RESPONSE_RTOL (relative) is a scale, anything else a different chain
RESPONSE_GRID_HZ = 1e-4
RESPONSE_GRID_N = 241
RESPONSE_RTOL = 1e-6
# the line of the run comment that holds a recipe build's provenance, as JSON
PROVENANCE_PREFIX = "provenance: "
# JSON's escape of "|" (a backslash, then u007c): mt_metadata splits a comment on "|"
_PIPE_ESCAPE = chr(92) + "u007c"


class _Span(NamedTuple):
    """Common span of the members.

    Attributes:
        t0 (int): First sample, ns since the epoch, UTC.
        n (int): Number of samples.
        fs (float): Sample rate in Hz.
    """

    t0: int
    n: int
    fs: float

    def iso(self, j: int) -> str:
        """Return the time of sample j in the ISO format of the stack metadata."""
        return _iso(self.t0 + int(round(j * (1e9 / self.fs))))


class _Chain(NamedTuple):
    """One channel's filter chain as processing resolves it, and its units.

    Attributes:
        filters (list): The mt_metadata filter objects, in stage order
            (`channel_response.filters_list`).
        applied (list): Whether each filter is marked applied; processing
            removes the applied ones only.
        names (list): The filters' names.
        units (str): The channel's units.
    """

    filters: list
    applied: list
    names: list
    units: str


class _Coil:
    """One member's coil on the common span, read from its HDF5 dataset on demand.

    ``coil[a:b]`` and ``coil[a:b:step]`` return samples a..b of the span,
    read from the dataset at the member's offset `i0`. No samples are
    cached. With a `scale` other than 1 the samples are returned as float64
    times the scale (the member brought onto the stack's reference chain,
    `calibration_plan`); with a scale of 1 they are returned as stored.

    Args:
        data: h5py dataset of the coil.
        i0 (int): Index in `data` of the span's first sample.
        n (int): Number of samples in the span.
        scale (float): Factor applied to every sample read.
    """

    def __init__(self, data, i0: int, n: int, scale: float = 1.0):
        self.data, self.i0, self.size, self.scale = data, int(i0), int(n), float(scale)

    def __getitem__(self, sl: slice) -> np.ndarray:
        a, b, step = sl.indices(self.size)
        x = self.data[self.i0 + a : self.i0 + b : step]
        if self.scale == 1.0:
            return x
        return np.asarray(x, dtype="float64") * self.scale


def _ns(t) -> int | None:
    """Convert a time (string or Timestamp, naive taken as UTC) to ns since the epoch; None passes through."""
    if t is None:
        return None
    ts = pd.Timestamp(t)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)


def _iso(ns: int) -> str:
    """Format ns since the epoch as ISO UTC to the microsecond, the format of the stack metadata."""
    return str(np.datetime_as_string(np.datetime64(int(ns), "ns"), unit="us")) + "+00:00"


def _text(comment) -> str:
    """Return the text of an mt_metadata Comment or a plain value, "" for None."""
    value = getattr(comment, "value", comment)
    return "" if value is None else str(value)


def _chunks(n: int, w: int) -> list[tuple[int, int]]:
    """Return (first, stop) sample pairs covering [0, n) in pieces of `w`, the last one partial."""
    return [(s, min(s + w, n)) for s in range(0, n, w)]


def _member_runs(survey: Survey, site: str, lo: int | None, hi: int | None, stack: ExitStack) -> tuple[Path, list]:
    """Open a site's processing archive and list its runs with hx and hy.

    Opens the archive read-only; `stack` closes it. `processing_archive`
    resolves the path: the site's filtered variant (built from its raw
    archive on demand when missing or stale) when the site declares
    filters, its raw archive otherwise. The member is therefore taken as
    processing sees it.

    Args:
        survey (Survey): The survey.
        site (str): Member site.
        lo (int or None): Window start, ns since the epoch.
        hi (int or None): Window end, ns since the epoch.
        stack (ExitStack): Owner of the open archive.

    Returns:
        tuple: ``(path, runs)``: the archive and, per run in the archive's
        order, a dict of ``run``, ``start`` (ns), ``n``, ``fs``,
        ``overlap`` (ns of [lo, hi) it covers, negative when none),
        ``comment``, ``hx``, ``hy`` (the h5py datasets) and ``chains``
        (``{coil: _Chain}``, each coil's filter chain and units).

    Raises:
        ValueError: If the site has no archive, no run with hx and hy, or a
            run whose hx and hy differ in grid.
    """
    try:
        path = processing_archive(survey, site)
    except FileNotFoundError:
        raise ValueError(
            f"{site}: no MTH5 archive; build it first (Build MTH5 on the "
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
            logger.warning(f"{site}: run {run_id} has no {'/'.join(COILS)}; skipped")
            continue
        grid, chains = {}, {}
        for c in COILS:
            ch = run.get_channel(c)
            grid[c] = (_ns(str(ch.metadata.time_period.start)), float(ch.metadata.sample_rate),
                       int(ch.hdf5_dataset.shape[0]), ch.hdf5_dataset)
            chains[c] = _read_chain(ch)
        if grid["hx"][:3] != grid["hy"][:3]:
            raise ValueError(f"{site} {run_id}: hx and hy do not share a sample grid "
                             f"(start ns, rate, samples: {grid['hx'][:3]} vs {grid['hy'][:3]})")
        start, fs, n, _ = grid["hx"]
        stop = start + n * 1e9 / fs  # one sample past the last
        overlap = min(stop, np.inf if hi is None else hi) - max(start, -np.inf if lo is None else lo)
        runs.append(dict(run=run_id, start=start, n=n, fs=fs, overlap=overlap, comment=_text(run.metadata.comments),
                         hx=grid["hx"][3], hy=grid["hy"][3], chains=chains))
    if not runs:
        raise ValueError(f"{site}: no run with hx and hy in {path}")
    return path, runs


def _read_chain(ch) -> _Chain:
    """Return a channel's filter chain as processing resolves it, with its applied flags, names and units.

    The filters are `channel_response.filters_list` (the archive's Filters
    group entries named by the channel's metadata, in stage order); a
    filter the group lacks is left out by mth5 with its own warning.
    """
    applied = {str(f.name).replace("/", " per ").lower(): bool(f.applied) for f in (ch.metadata.filters or [])}
    filters = list(ch.channel_response.filters_list)
    units = ch.metadata.units
    return _Chain(filters, [applied.get(f.name, True) for f in filters], [f.name for f in filters],
                  "" if units is None else str(units))


def _total_response(chain: _Chain, freqs: np.ndarray) -> np.ndarray:
    """Return the product of a chain's applied filters' complex responses on `freqs` (1 where none is applied).

    mt_metadata's logging is off while the responses are evaluated: a
    response table warns on every evaluation past its ends.
    """
    resp = np.ones(freqs.size, dtype=complex)
    logger.disable("mt_metadata")
    try:
        for f, applied in zip(chain.filters, chain.applied):
            if applied:
                resp = resp * np.asarray(f.complex_response(freqs), dtype=complex)
    finally:
        logger.enable("mt_metadata")
    return resp


def _unit_key(units) -> str:
    """Return a spelling-blind key of a unit name: "nT", "nanoTesla" and "nano tesla" give "nt"."""
    key = "".join(str(units or "").lower().split()).replace("_", "").replace("-", "")
    return {"nanotesla": "nt", "microvolt": "uv", "microvolts": "uv", "millivolt": "mv", "volt": "v",
            "tesla": "t"}.get(key, key)


def _calibrated_units(chain: _Chain) -> str:
    """Return the units a chain calibrates to: the units_in of its first applied filter ("" without one)."""
    for f, applied in zip(chain.filters, chain.applied):
        if applied:
            return str(getattr(f, "units_in", "") or "")
    return ""


def calibration_plan(runs: dict, per_comp: dict, fs: float, name: str = "stack") -> dict:
    """Decide the filter chain each coil of a stack carries and the scale that puts each member on it.

    Per coil, the first member in `per_comp` order is the reference. Every
    member's total response (`_total_response`, what processing divides by)
    is divided by the reference's on `RESPONSE_GRID_N` log-spaced
    frequencies from `RESPONSE_GRID_HZ` to `fs / 2`. A ratio that is a real
    constant to `RESPONSE_RTOL` of itself is a scale: the member's samples
    are to be multiplied by its inverse (exactly 1 when the ratio is 1 to
    the tolerance, so a stack of like members multiplies nothing). A ratio
    that varies with frequency, or is complex, is another chain, and the
    stack is refused: its one chain could not describe such a member.

    A member with no chain beside members with one is an identity member
    when its channel's units are the units the reference chain calibrates
    to (`_calibrated_units`, compared by `_unit_key`): its response is 1,
    and its ratio to the reference must pass the same test (so the
    reference chain must be a real constant); its scale is then R_ref. The
    reference is the first member with a chain.

    Args:
        runs (dict): Member to its run (`_member_runs`'s dict, with
            ``chains``).
        per_comp (dict): The members per coil, in the order given.
        fs (float): The members' sample rate in Hz.
        name (str): The stack's name, for messages.

    Returns:
        dict: Per coil, None when no member of the coil carries a chain
        (the stack's coil is then written uncalibrated, and a warning says
        so), else ``{"reference", "filters", "applied", "names", "units",
        "scales", "identity"}``: the reference member, its chain (filter
        objects, applied flags, names) and units, ``{member: scale}``, and
        ``{member: units}`` of the identity members ({} without one).

    Raises:
        ValueError: If a member carries no chain where another does and its
            units are not those the reference chain calibrates to, or the
            reference chain varies with frequency; or a member's response
            differs from the reference's in shape.
    """
    freqs = np.logspace(np.log10(RESPONSE_GRID_HZ), np.log10(float(fs) / 2.0), RESPONSE_GRID_N)
    plan = {}
    for comp in COILS:
        members = list(per_comp[comp])
        chains = {m: runs[m]["chains"][comp] for m in members}
        with_chain = [m for m in members if chains[m].filters]
        if not with_chain:
            plan[comp] = None
            logger.warning(
                f"{name}: {comp}: no member carries a filter chain, so the stack's {comp} is written uncalibrated "
                f"(digital counts, no filters): a transfer function estimated against it has errors scaled by "
                f"1 / the members' gain (docs/upstream_issues.md 111)")
            continue
        without = [m for m in members if m not in with_chain]
        ref = with_chain[0]  # members[0] unless it is an identity member
        physical = _calibrated_units(chains[ref])
        identity = {}
        for m in without:
            if not physical or _unit_key(chains[m].units) != _unit_key(physical):
                raise ValueError(
                    f"{name}: {comp}: {m} carries no filter chain where {', '.join(with_chain)} "
                    f"do{'es' if len(with_chain) == 1 else ''}, and its samples are in {chains[m].units or 'no units'!r}, "
                    f"not {physical or '?'!r}, the units {ref}'s chain ({', '.join(chains[ref].names)}) calibrates "
                    f"to: a stack carries one chain, so ingest every member with its calibration, stack members "
                    f"that carry none, or give {m}'s channels the calibrated units")
            identity[m] = chains[m].units
        reference = _total_response(chains[ref], freqs)
        scales = {}
        for m in members:
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = _total_response(chains[m], freqs) / reference
            c = complex(np.mean(ratio)) if np.all(np.isfinite(ratio)) else complex(np.nan)
            spread = float(np.max(np.abs(ratio - c))) if np.isfinite(c) else np.inf
            bad = not np.isfinite(spread) or spread > RESPONSE_RTOL * abs(c) or abs(c.imag) > RESPONSE_RTOL * abs(c)
            if bad and m in identity:
                raise ValueError(
                    f"{name}: {comp}: {m} carries no filter chain (samples in {identity[m]} taken as calibrated, "
                    f"an identity chain), but the chain of {ref} ({', '.join(chains[ref].names)}) is not a real "
                    f"constant over {RESPONSE_GRID_HZ:g}-{fs / 2:g} Hz (its response spans "
                    f"{spread / abs(c) if abs(c) > 0 else np.inf:.3g} of its mean): one chain cannot describe both, "
                    f"so leave {m} out or give it {ref}'s chain")
            if bad:
                raise ValueError(
                    f"{name}: {comp}: the filter chain of {m} ({', '.join(chains[m].names)}) and that of {ref} "
                    f"({', '.join(chains[ref].names)}) differ in frequency response (their ratio spans "
                    f"{spread / abs(c) if abs(c) > 0 else np.inf:.3g} of its mean {abs(c):.6g}, phase "
                    f"{np.degrees(np.angle(c)) if abs(c) > 0 else np.nan:.3g} deg, over {RESPONSE_GRID_HZ:g}-"
                    f"{fs / 2:g} Hz): a stack carries one chain, so stack members of one coil model and response "
                    f"table, or leave {m} out")
            scales[m] = 1.0 if abs(c.real - 1.0) <= RESPONSE_RTOL else 1.0 / c.real
        units = chains[ref].units or str(chains[ref].filters[-1].units_out)
        other_units = sorted({chains[m].units for m in members if m not in identity} - {chains[ref].units})
        if other_units:
            logger.warning(f"{name}: {comp}: the members' units differ ({chains[ref].units!r} at {ref}, "
                           f"{', '.join(repr(u) for u in other_units)} elsewhere); the stack takes {ref}'s")
        plan[comp] = {"reference": ref, "filters": list(chains[ref].filters), "applied": list(chains[ref].applied),
                      "names": list(chains[ref].names), "units": units, "scales": scales, "identity": identity}
        scaled = ", ".join(f"{m} x{s:.9g}" for m, s in scales.items() if s != 1.0)
        logger.info(f"{name}: {comp}: chain of {ref} ({', '.join(chains[ref].names)}) in {units}"
                    + (f"; scaled onto it: {scaled}" if scaled else "; every member on its scale")
                    + "".join(f"; {_identity_text(m, u)}" for m, u in identity.items()))
    return plan


def _identity_text(member: str, units: str) -> str:
    """Return the record of an identity member: "member CNB: no filter chain, samples in nanoTesla taken as calibrated"."""
    return f"member {member}: no filter chain, samples in {units} taken as calibrated"


def _same_plan(a: dict, b: dict) -> bool:
    """Return whether two calibration plans name the same chains, units and scales."""
    for comp in COILS:
        pa, pb = a.get(comp), b.get(comp)
        if (pa is None) != (pb is None):
            return False
        if pa is None:
            continue
        if (pa["reference"], pa["names"], pa["applied"], pa["units"]) != (pb["reference"], pb["names"],
                                                                         pb["applied"], pb["units"]):
            return False
        if pa.get("identity", {}) != pb.get("identity", {}):
            return False
        if set(pa["scales"]) != set(pb["scales"]) or not all(
                np.isclose(pa["scales"][m], pb["scales"][m], rtol=RESPONSE_RTOL, atol=0.0) for m in pa["scales"]):
            return False
    return True


def _calibration_line(plan: dict) -> str | None:
    """Return the run comment's calibration line, or None when no coil carries a chain."""
    parts = []
    for comp in COILS:
        p = plan.get(comp)
        if p is None:
            continue
        scales = ", ".join(f"{m} x{s:.9g}" for m, s in p["scales"].items())
        parts.append(f"{comp} chain of {p['reference']} ({', '.join(p['names'])}) in {p['units']}, scales {scales}"
                     + "".join(f", {_identity_text(m, u)}" for m, u in p.get("identity", {}).items()))
    if not parts:
        return None
    return ("calibration: " + "; ".join(parts)).replace("|", "/")


def _filters_note(survey: Survey, site: str, run: dict) -> None:
    """Warn when filters.yaml and the archive's run disagree on whether filters were applied."""
    declared = [s for s in (getattr(survey.site(site), "filters", None) or []) if s]
    recorded = "ingest filters (in order)" in run["comment"]
    if bool(declared) != recorded:
        logger.warning(
            f"{site}: filters.yaml declares {len(declared)} filter(s) but the archive's run "
            f"{run['run']} records {'some' if recorded else 'none'}; the stack takes the "
            f"archive as it is; rebuild the archive if it is stale"
        )


def _member_run(survey: Survey, site: str, lo: int | None, hi: int | None, stack: ExitStack) -> dict:
    """Open a site's processing archive and pick the run overlapping [lo, hi) most.

    The runs are `_member_runs`'s; on a tie the first in the archive's
    order is taken.

    Args:
        survey (Survey): The survey.
        site (str): Member site.
        lo (int or None): Window start, ns since the epoch.
        hi (int or None): Window end, ns since the epoch.
        stack (ExitStack): Owner of the open archive.

    Returns:
        dict: ``run``, ``start`` (ns), ``n``, ``fs``, ``overlap``,
        ``comment`` and ``hx``, ``hy`` (the h5py datasets).

    Raises:
        ValueError: If the site has no archive, no run with hx and hy, a run
            whose hx and hy differ in grid, or no run overlapping the window.
    """
    path, runs = _member_runs(survey, site, lo, hi, stack)
    best = max(runs, key=lambda r: r["overlap"])
    if best["overlap"] <= 0:
        raise ValueError(f"{site}: no run in {path} overlaps the stack's window")
    if len(runs) > 1:
        n_in = sum(r["overlap"] > 0 for r in runs)
        logger.info(f"{site}: using run {best['run']} of {len(runs)} in {path.name} "
                    f"({n_in} overlap the window; {best['overlap'] / 3.6e12:.2f} h of it in this one)")
    _filters_note(survey, site, best)
    return best


def _per_comp(members) -> dict[str, list[str]]:
    """Return the member lists per coil from a list (both coils) or a {coil: list} dict."""
    per_comp = members if isinstance(members, dict) else {"hx": list(members), "hy": list(members)}
    return {c: list(v) for c, v in per_comp.items()}


def _open_members(survey: Survey, per_comp: dict, start, end, name: str, stack: ExitStack):
    """Open every member and compute the common span.

    Each member's run is the one overlapping [start, end) most. The common
    span is the intersection of those runs with [start, end), on the grid
    of the latest-starting run.

    Returns:
        tuple: ``(members, coils, span, plan)``: the sorted member list,
        ``{coil: {member: _Coil}}`` in `per_comp` order (each member on
        the reference's scale), the `_Span`, and the `calibration_plan`.

    Raises:
        ValueError: If the sample rates differ, a run start lies more than
            `GRID_TOL` of a sample off the common grid, the members do not
            overlap in [start, end), or their chains cannot be put on one
            (`calibration_plan`).
    """
    all_members = sorted(set(per_comp["hx"]) | set(per_comp["hy"]))
    lo, hi = _ns(start), _ns(end)
    runs = {m: _member_run(survey, m, lo, hi, stack) for m in all_members}
    plan = calibration_plan(runs, per_comp, runs[all_members[0]]["fs"], name)
    coils, span = _align(runs, per_comp, lo, hi, name, f"[{start}, {end})", plan)
    logger.info(f"{name}: common span {span.iso(0)} .. {span.iso(span.n - 1)} ({span.n} samples, "
                f"{span.n / span.fs / 3600:.2f} h at {span.fs:g} Hz) from {len(all_members)} archives")
    return all_members, coils, span, plan


def _align(runs: dict, per_comp: dict, lo: int | None, hi: int | None, name: str, where: str,
           plan: dict | None = None):
    """Put one run per member on a common grid over [lo, hi).

    The span is the intersection of the runs with [lo, hi), on the grid of
    the latest-starting run.

    Args:
        runs (dict): Member to its run (`_member_runs`'s dict).
        per_comp (dict): The members per coil.
        lo, hi (int or None): The window, ns since the epoch.
        name (str): The stack's name, for messages.
        where (str): The window as the "do not overlap" message names it.
        plan (dict, optional): The `calibration_plan`; each coil's members
            are read through its scales. None reads every member as stored.

    Returns:
        tuple: ``(coils, span)``: ``{coil: {member: _Coil}}`` in `per_comp`
        order, and the `_Span`.

    Raises:
        ValueError: If the sample rates differ, a run start lies more than
            `GRID_TOL` of a sample off the common grid, or the runs do not
            overlap in [lo, hi).
    """
    members = sorted(runs)
    fs = runs[members[0]]["fs"]
    if any(abs(r["fs"] - fs) > 1e-9 * fs for r in runs.values()):
        raise ValueError(f"{name}: members' sample rates differ: "
                         + ", ".join(f"{m} {r['fs']:g} Hz" for m, r in runs.items()))
    anchor = max(members, key=lambda m: runs[m]["start"])
    a0 = runs[anchor]["start"]
    # the first sample of the anchor's grid at or after `lo`
    k0 = 0 if lo is None or lo <= a0 else int(np.ceil((lo - a0) / 1e9 * fs - GRID_TOL))
    offsets = {}
    for m in members:
        pos = (a0 - runs[m]["start"]) / 1e9 * fs + k0
        offsets[m] = int(round(pos))
        if abs(pos - offsets[m]) > GRID_TOL:
            raise ValueError(
                f"{m}: sample grid does not align with the stack (its run {runs[m]['run']} starts "
                f"{pos - offsets[m]:+.4f} samples off {anchor}'s grid): GPS timing "
                f"assumption violated; investigate before stacking"
            )
    n = min(runs[m]["n"] - offsets[m] for m in members)
    if hi is not None:
        n = min(n, int(np.ceil((hi - a0) / 1e9 * fs - k0 - GRID_TOL)))
    if n <= 0:
        raise ValueError(f"{name}: members do not overlap in {where}")
    span = _Span(a0 + int(round(k0 * (1e9 / fs))), n, fs)
    scales = {c: (plan[c]["scales"] if plan and plan.get(c) else {}) for c in COILS}
    coils = {c: {m: _Coil(runs[m][c], offsets[m], n, scales[c].get(m, 1.0)) for m in per_comp[c]} for c in COILS}
    return coils, span


def _run_stop(run: dict) -> float:
    """Return one sample past a run's last sample, ns since the epoch."""
    return run["start"] + run["n"] * 1e9 / run["fs"]


def stack_pieces(member_runs: dict, lo: int | None = None, hi: int | None = None) -> list[tuple]:
    """Split a window into the stretches in which every member is inside one of its runs.

    Each stretch (a piece) is the intersection of one run per member with
    [lo, hi); members' runs do not overlap one another, so the pieces do
    not either. A member with a gap costs the stack that gap, not the
    stretch on either side of it.

    Args:
        member_runs (dict): Member to its runs, each a dict with ``start``
            (ns), ``n`` and ``fs`` (as `_member_runs` gives them).
        lo, hi (int or None): The window, ns since the epoch; None for no
            bound.

    Returns:
        list: ``(start_ns, stop_ns, {member: run})`` per piece, earliest
        first; stop is exclusive; [] when the members share no time.
    """
    pieces = [(-np.inf if lo is None else lo, np.inf if hi is None else hi, {})]
    for m in sorted(member_runs):
        nxt = []
        for a, b, chosen in pieces:
            for r in member_runs[m]:
                s, e = max(a, r["start"]), min(b, _run_stop(r))
                if e > s:
                    nxt.append((s, e, {**chosen, m: r}))
        pieces = nxt
    return sorted(pieces, key=lambda p: p[0])


def _open_pieces(survey: Survey, per_comp: dict, start, end, name: str, stack: ExitStack, min_piece_s: float):
    """Open every member and compute the common span of each piece of the window.

    Every run of each member with hx and hy is taken (`_member_runs`), the
    window is split into `stack_pieces`, and each piece of at least
    `min_piece_s` is put on its own common grid (`_align`); shorter ones
    are left out.

    Returns:
        tuple: ``(members, kept, dropped, plan)``: the sorted member list;
        per kept piece ``(coils, span, {member: run id})`` in time order;
        per piece left out ``(start_ns, stop_ns)``; the `calibration_plan`
        of the pieces' runs (every kept piece must give the same).

    Raises:
        ValueError: If a member has no archive or no run with hx and hy, a
            piece's runs differ in rate or grid, no piece is long enough,
            the members' chains cannot be put on one, or two pieces differ
            in chain or scale.
    """
    all_members = sorted(set(per_comp["hx"]) | set(per_comp["hy"]))
    lo, hi = _ns(start), _ns(end)
    member_runs = {}
    for m in all_members:
        path, runs = _member_runs(survey, m, lo, hi, stack)
        inside = [r for r in runs if r["overlap"] > 0]
        if not inside:
            raise ValueError(f"{m}: no run in {path} overlaps the stack's window")
        _filters_note(survey, m, max(inside, key=lambda r: r["overlap"]))
        member_runs[m] = inside
    kept, dropped, plan = [], [], None
    for a, b, chosen in stack_pieces(member_runs, lo, hi):
        if (b - a) / 1e9 < min_piece_s:
            dropped.append((int(a), int(b)))
            continue
        piece_plan = calibration_plan(chosen, per_comp, chosen[all_members[0]]["fs"], name)
        if plan is None:
            plan = piece_plan
        elif not _same_plan(plan, piece_plan):
            raise ValueError(f"{name}: the piece from {_iso(int(a))} takes a different chain or scale from the "
                             f"members' runs than the first piece: a stack archive carries one chain per coil")
        coils, span = _align(chosen, per_comp, int(a), int(np.ceil(b)), name,
                             f"[{_iso(int(a))}, {_iso(int(np.ceil(b)))})", plan)
        kept.append((coils, span, {m: r["run"] for m, r in chosen.items()}))
    for a, b in dropped:
        logger.info(f"{name}: piece {_iso(a)} .. {_iso(b)} ({(b - a) / 3.6e12:.2f} h) is under "
                    f"{min_piece_s / 3600:g} h: left out")
    if not kept:
        raise ValueError(f"{name}: members do not share {min_piece_s / 3600:g} h of data in [{start}, {end}) "
                         f"({len(dropped)} shorter piece(s), {sum(b - a for a, b in dropped) / 3.6e12:.2f} h)")
    for k, (_, span, _) in enumerate(kept, 1):
        logger.info(f"{name}: piece {k} of {len(kept)}: {span.iso(0)} .. {span.iso(span.n - 1)} ({span.n} samples, "
                    f"{span.n / span.fs / 3600:.2f} h at {span.fs:g} Hz)")
    return all_members, kept, dropped, plan


def _median(a, n: int | None = None) -> float:
    """Estimate a member's DC offset as the median of an even subsample of its first `n` samples.

    The subsample keeps at most about a million samples; on an archived
    coil it is one strided read of the HDF5 dataset.
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
    """Compute each member's band-averaged squared coherence with the mean of the others, per chunk.

    Each member's median over the whole span is removed, the leave-one-out
    mean of the others is formed chunk by chunk, and each chunk's pair goes
    through `mt_workbench.timefreq.cascade` on the ladder planned for the whole
    span (`levels_plan` with window = step = `chunk_s`, periods from the
    shortest band edge to the longest), which gives every level exactly one
    window, the chunk. Each band's value is `band_from_levels`: the mean of
    the band's log-period bins on each level, averaged over the levels
    reaching the band. Over 0.1-10 s at 1000 Hz these are levels 0, 1 and 2
    (0.1-1, 1-4 and 4-10 s), weighted equally. Level 0 matches a whole-span
    cascade; the decimated levels see the chunk's own edges rather than its
    neighbours' samples (the FIR reaches about 200 input samples each side).

    Args:
        arrays (dict): One coil, ``{member: 1-D array or _Coil}``, all on
            the same sample grid. Each chunk is read separately.
        sample_rate (float): Sample rate in Hz.
        bands (tuple): ``(pmin_s, pmax_s)`` period bands.
        chunk_s (float): Chunk length in s.

    Returns:
        tuple: ``(chunk_starts, {band: gamma2[member, chunk]})`` with members
        in `arrays` order. Samples after the last whole chunk belong to no
        chunk; the stack gives them the last chunk's weights.

    Raises:
        ValueError: With fewer than two members, or when a `chunk_s` chunk
            cannot carry the band ladder on this record.
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
    # the cascade logs its ladder on every call, so its logging is off inside the loop
    logger.disable("mt_workbench.timefreq")
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
        logger.enable("mt_workbench.timefreq")
    return np.arange(n_chunks) * w, out


def coherence_weights(gamma2: np.ndarray, floor: float = WEIGHT_FLOOR) -> np.ndarray:
    """Convert coherences to stack weights, each chunk summing to one.

    Each chunk's gamma2 is normalised to sum to one; a member whose
    normalised weight is under `floor` gets weight 0 and the rest are
    renormalised. A NaN gamma2 counts as 0. A chunk where every gamma2 is 0
    or NaN gets equal weights, and a chunk where every member would be
    dropped (possible only with more than 1/floor members) keeps its
    undropped weights; both cases are logged.

    Args:
        gamma2 (np.ndarray): Coherence, shape (member, chunk).
        floor (float): Smallest normalised weight kept.

    Returns:
        np.ndarray: Weights, shape (member, chunk).
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
    """Return one coil's plain mean of its members' counts (float64), computed chunk by chunk."""
    n = min(a.size for a in arrays.values())
    acc_all = np.zeros(n, dtype="float64")
    for s, e in _chunks(n, int(round(WEIGHT_CHUNK_S * sample_rate))):
        acc = np.zeros(e - s, dtype="float64")
        for a in arrays.values():
            acc += np.asarray(a[s:e], dtype="float64")
        acc_all[s:e] = acc / len(arrays)
    return acc_all


def _coherence_stack(arrays: dict, sample_rate: float) -> tuple[np.ndarray, dict]:
    """Build one coil's coherence-weighted stack, medians removed.

    Makes two passes over the members: `member_coherence` for the weights,
    then the weighted sum chunk by chunk. The partial last chunk takes the
    last whole chunk's weights.

    Returns:
        tuple: ``(stack, info)`` with ``info`` holding ``members``,
        ``chunk_starts``, ``bands``, ``gamma2`` and ``weights``.
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
        kk = min(k, last)  # the tail uses the last whole chunk's weights
        for i, m in enumerate(members):
            if weights[i, kk] > 0:
                acc[s:e] += weights[i, kk] * (np.asarray(arrays[m][s:e], dtype="float64") - offsets[m])
    info = {"members": members, "chunk_starts": starts, "bands": bands,
            "gamma2": gamma2, "weights": weights}
    return acc, info


def stack_arrays(arrays: dict, sample_rate: float, weighting: str = "none") -> tuple[np.ndarray, dict]:
    """Stack one coil of the members, as `build_synthetic_remote` does.

    The members are anything sliced as ``a[s:e]`` with a ``size``: numpy
    arrays (the GUI's member check reads a bounded span) or the archive's
    coils. ``"none"`` is the plain mean of the counts (`_mean_stack`, no
    offset removed); ``"coherence"`` the coherence-weighted sum with the
    medians removed (`_coherence_stack`).

    Args:
        arrays (dict): Member name to its samples on one grid.
        sample_rate (float): Sample rate in Hz.
        weighting (str): One of `WEIGHTINGS`.

    Returns:
        tuple: ``(stack, info)``: the float64 stack over the shortest
        member, and ``{}`` for ``"none"`` or `_coherence_stack`'s
        ``members``, ``chunk_starts``, ``bands``, ``gamma2`` and ``weights``.

    Raises:
        ValueError: If `weighting` is not one of `WEIGHTINGS`.
    """
    if weighting not in WEIGHTINGS:
        raise ValueError(f"weighting {weighting!r} is not one of {WEIGHTINGS}")
    if weighting == "none":
        return _mean_stack(arrays, sample_rate), {}
    return _coherence_stack(arrays, sample_rate)


def _weights_comments(infos: dict, t0: str) -> tuple[str, dict[str, str]]:
    """Build the comments of a coherence-weighted stack.

    Returns:
        tuple: ``(run_comment, {coil: channel_comment})``. The run comment
        states the rule and the mean weights; each channel comment lists the
        per-chunk weights in per mille.
    """
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
        f"coherence-weighted stack (mt_workbench.virtual, weighting=coherence). Rule: per member, "
        f"per {WEIGHT_CHUNK_S:g} s chunk, per coil, weight = band-averaged squared coherence "
        f"({lo:g}-{hi:g} s, mt_workbench.timefreq cascade) of the member's coil with the mean of the "
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


def _provenance_line(provenance: dict) -> str:
    """Return the run comment's provenance line for a recipe build.

    The JSON has sorted keys and no spaces, is ASCII, and holds no raw
    "|" or newline, so the comment keeps it whole and `recorded_provenance`
    finds it as the line that starts with `PROVENANCE_PREFIX`.

    Raises:
        ValueError: If the recipe or its hash is missing, empty or holds a
            "|", or the dict is not JSON.
    """
    for key in ("recipe", "recipe_hash"):
        value = provenance.get(key) if isinstance(provenance, dict) else None
        if not isinstance(value, str) or not value or "|" in value:
            raise ValueError(f"provenance needs a {key} (text without '|'), got {value!r}")
    try:
        text = json.dumps(provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"provenance is not JSON: {exc}") from None
    return PROVENANCE_PREFIX + text.replace("|", _PIPE_ESCAPE)


def recorded_provenance(path, survey_name: str, name: str) -> dict | None:
    """Return the provenance a recipe build wrote into a stack archive.

    Reads the station's run comments with h5py, read-only and without the
    HDF5 file lock, so an archive another reader holds can be read. The
    provenance is the JSON of the last comment line that starts with
    `PROVENANCE_PREFIX`.

    Args:
        path: The stack's MTH5 archive.
        survey_name (str): The survey's name (made a group name as mth5 makes it).
        name (str): The stack's station name.

    Returns:
        dict or None: The provenance as given to `build_synthetic_remote`;
        None for no file, no station, no run with such a line, or a line
        whose JSON does not read.
    """
    path = Path(path)
    if not path.exists():
        return None
    key = f"Experiment/Surveys/{validate_name(survey_name)}/Stations/{validate_name(name)}"
    with h5py.File(path, "r", locking=False) as f:
        station = f.get(key)
        if not isinstance(station, h5py.Group):
            return None
        for run_id in sorted(station.keys()):
            run = station.get(run_id)
            if not isinstance(run, h5py.Group):
                continue
            text = run.attrs.get("comments")
            if isinstance(text, bytes):
                text = text.decode("utf-8", "replace")
            if not isinstance(text, str):
                continue
            lines = [line for line in text.split("\n") if line.startswith(PROVENANCE_PREFIX)]
            if not lines:
                continue
            try:
                value = json.loads(lines[-1][len(PROVENANCE_PREFIX):])
            except ValueError:
                logger.warning(f"{path.name} {name} {run_id}: the provenance line does not read as JSON")
                return None
            return value if isinstance(value, dict) else None
    return None


def check_members(survey: Survey, members, start, end, name: str = "check") -> dict:
    """Check the members of a stack before building it.

    Each member's coil is compared with the plain mean of the other
    members' same coil, per `WEIGHT_CHUNK_S` chunk, in `CHECK_BANDS_S`, on
    the common span `build_synthetic_remote` would stack. Members are read
    as processing sees them. A dead coil sits near
    0 in every band.

    Args:
        survey (Survey): The survey.
        members (list or dict): Member sites, as for `build_synthetic_remote`.
        start: Window start.
        end: Window end.
        name (str): Label for log lines.

    Returns:
        dict: ``{coil: {"members", "chunk_starts", "bands"}}`` with
        ``bands`` mapping each band to gamma2[member, chunk].
    """
    per_comp = _per_comp(members)
    out = {}
    with ExitStack() as stack:
        _, coils, span, _ = _open_members(survey, per_comp, start, end, name, stack)
        for comp in COILS:
            starts, bands = member_coherence(coils[comp], span.fs, bands=CHECK_BANDS_S)
            out[comp] = {"members": list(per_comp[comp]), "chunk_starts": starts, "bands": bands}
    return out


def _concat_infos(pieces_infos: list) -> dict:
    """Join the per-piece weights of a piece-wise coherence build along the chunk axis, per coil.

    Every piece holds every member, so the member order is the same; the
    chunk starts are each piece's own sample offsets, in piece order.
    """
    if len(pieces_infos) == 1:
        return pieces_infos[0]
    out = {}
    for comp in pieces_infos[0]:
        parts = [p[comp] for p in pieces_infos]
        out[comp] = {
            "members": parts[0]["members"],
            "chunk_starts": np.concatenate([p["chunk_starts"] for p in parts]),
            "bands": {b: np.hstack([p["bands"][b] for p in parts]) for b in parts[0]["bands"]},
            "gamma2": np.hstack([p["gamma2"] for p in parts]),
            "weights": np.hstack([p["weights"] for p in parts]),
        }
    return out


def _rate_label(fs: float) -> str:
    """Return the sample rate as a run id writes it: 1000, 10, 1, or 0p1 for 0.1 Hz."""
    return f"{int(fs)}" if float(fs).is_integer() else f"{fs:g}".replace(".", "p")


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
    provenance: dict | None = None,
    min_piece_h: float | None = None,
    pieces_out: list | None = None,
    calibration_out: dict | None = None,
) -> Path:
    """Stack members' archived hx and hy into a virtual station MTH5 that carries their calibration.

    Each member is read from its processing archive
    (`mt_workbench.ingest.processing_archive`), as processing sees it; the
    declared filters were applied at ingest. The stack's hx and hy carry
    the members' common filter chain and units (Calibration in the module
    docstring; `calibration_plan`): members whose responses differ from
    the first listed member's by a constant are scaled onto it, members
    whose responses differ in shape refuse the build, and members with no
    chain give an uncalibrated stack. By default each member gives
    the run that overlaps [start, end) most, and the stack is one run over
    the intersection of those runs with [start, end). With `min_piece_h`
    the stack is built per piece: every run of every member is taken, and
    each stretch of [start, end) in which every member is inside one of its
    runs (`stack_pieces`) becomes one run of the archive, so a member with
    a gap or a restart costs the stack that gap only; a piece shorter than
    `min_piece_h` hours is left out and logged. Each run is streamed in
    `WEIGHT_CHUNK_S` chunks. With ``weighting="none"`` each coil is the
    plain mean of its members over the run's span; with ``"coherence"`` it
    is the chunk-wise coherence-weighted sum described in the module
    docstring, its weights computed per run. The runs are named
    ``sr<rate>_0001``, ``sr<rate>_0002``, ... after the members' rate
    (sr10_0001 at 10 Hz, sr1_0001 at 1 Hz).

    Args:
        survey (Survey): The survey.
        members (list or dict): Sites used for both coils, or
            ``{"hx": [...], "hy": [...]}`` with a member list per coil, for
            a coherence-selected stack in which a site with a dead hy still
            contributes its hx, and vice versa.
        start: Window start.
        end: Window end.
        name (str): Station id of the virtual station.
        out_path (Path, optional): Output file; default
            ``<workspace>/mth5/<name>.h5``.
        overwrite (bool): Replace an existing file. When False, an existing
            file is returned as it is.
        weighting (str): ``"none"`` or ``"coherence"``.
        weights_out (dict, optional): Receives
            ``{coil: {"members", "chunk_starts", "bands", "gamma2",
            "weights"}}`` from a coherence-weighted build (a piece-wise
            build's pieces joined along the chunk axis); left unchanged for
            an unweighted build or a reused file.
        provenance (dict, optional): A recipe build's record (Provenance in
            the module docstring), holding at least ``recipe`` and
            ``recipe_hash``; any JSON value. Written to the station and run
            comments; it changes no sample. None writes neither.
        min_piece_h (float, optional): Build per piece, leaving out pieces
            shorter than this many hours; None (the default) builds one run
            from one run per member.
        pieces_out (list, optional): Receives, for a piece-wise build, one
            dict per piece in time order: ``start``, ``end`` (ISO UTC; end
            exclusive for a piece left out, the last sample for one kept),
            ``hours``, ``kept`` and ``runs`` (member to run id; None for a
            piece left out).
        calibration_out (dict, optional): Receives, per coil, None for a
            coil written uncalibrated, else ``reference`` (the member whose
            chain the coil carries), ``names`` (its filters), ``units``,
            ``scales`` (member to the factor its samples were multiplied
            by) and ``identity`` (member to units, the members with no
            chain taken as calibrated); left unchanged for a reused file.

    Returns:
        Path: The MTH5 file.

    Raises:
        ValueError: If `weighting` is unknown, `provenance` lacks the
            recipe or its hash or is not JSON, `min_piece_h` is not
            positive, a member has no archive, the members' grids or spans
            do not match, their filter chains cannot be put on one
            (`calibration_plan`), or (piece-wise) no piece is `min_piece_h`
            long.
    """
    if weighting not in WEIGHTINGS:
        raise ValueError(f"weighting {weighting!r} is not one of {WEIGHTINGS}")
    if min_piece_h is not None and not min_piece_h > 0:
        raise ValueError(f"min_piece_h takes a positive number of hours; given {min_piece_h!r}")
    provenance_line = _provenance_line(provenance) if provenance is not None else None
    out_path = Path(out_path) if out_path else survey.workspace / "mth5" / f"{name}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        if not overwrite:
            logger.info(f"{out_path} exists; reusing (overwrite=False)")
            return out_path
        out_path.unlink()

    per_comp = _per_comp(members)
    how = "mean" if weighting == "none" else "coherence-weighted sum"
    built = []  # per run of the archive: (span, {coil: stack}, {coil: info}, {member: run id} or None)
    dropped = []
    with ExitStack() as stack:
        if min_piece_h is None:
            all_members, coils, span, plan = _open_members(survey, per_comp, start, end, name, stack)
            pieces = [(coils, span, None)]
        else:
            all_members, pieces, dropped, plan = _open_pieces(survey, per_comp, start, end, name, stack,
                                                              float(min_piece_h) * 3600.0)
        for coils, span, used in pieces:
            total, infos = {}, {}
            for comp in COILS:
                total[comp], info = stack_arrays(coils[comp], span.fs, weighting)
                if info:
                    infos[comp] = info
                logger.info(f"{name}: {comp} = {how} of {per_comp[comp]} ({span.n} samples)")
            built.append((span, total, infos, used))
    members = all_members
    if weights_out is not None and built[0][2]:
        weights_out.update(_concat_infos([b[2] for b in built]))
    if pieces_out is not None and min_piece_h is not None:
        rows = [dict(start=span.iso(0), end=span.iso(span.n - 1), hours=span.n / span.fs / 3600.0, kept=True,
                     runs=dict(used)) for span, _, _, used in built]
        rows += [dict(start=_iso(a), end=_iso(b), hours=(b - a) / 3.6e12, kept=False, runs=None) for a, b in dropped]
        pieces_out.extend(sorted(rows, key=lambda r: r["start"]))
    if calibration_out is not None:
        calibration_out.update({c: None if plan.get(c) is None else {k: plan[c][k] for k in
                                                                        ("reference", "names", "units", "scales",
                                                                         "identity")}
                                for c in COILS})
    calibration_line = _calibration_line(plan)

    # centroid location for metadata
    lats = [survey.site(m).latitude for m in members if survey.site(m).latitude]
    lons = [survey.site(m).longitude for m in members if survey.site(m).longitude]

    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        survey_group = m.add_survey(survey.name)
        station_group = m.add_station(name, survey=survey.name)
        if lats and lons:
            station_group.metadata.location.latitude = float(np.mean(lats))
            station_group.metadata.location.longitude = float(np.mean(lons))
        if calibration_line is None:
            what = "raw hx/hy counts"
            calibrated = ("uncalibrated: the members carry no filter chain (the remote-reference estimate is "
                          "invariant to the remote's calibration, its errors are not: upstream issue 111)")
        else:
            what = "hx/hy"
            chains = "; ".join(f"{c} {', '.join(plan[c]['names'])} in {plan[c]['units']}" for c in COILS if plan.get(c))
            calibrated = (f"calibrated: hx and hy carry the members' common filter chain ({chains}), applied by "
                          f"processing as a member's is (upstream issue 111)")
            ident = sorted({(m, u) for c in COILS if plan.get(c) for m, u in plan[c].get("identity", {}).items()})
            if ident:
                calibrated += "; " + "; ".join(_identity_text(m, u) for m, u in ident)
        if weighting == "none":
            station_comment = f"synthetic remote: mean of {what} from {', '.join(members)}; {calibrated}"
        else:
            station_comment = (
                f"synthetic remote: coherence-weighted stack of {what} (medians removed) from {', '.join(members)}; "
                f"{calibrated}; weights in the run and channel comments"
            )
        filters_group = survey_group.filters_group
        for comp in COILS:
            for f in (plan[comp]["filters"] if plan.get(comp) else []):
                filters_group.add_filter(f)  # an existing name is kept, so hx and hy may share a filter
        if min_piece_h is not None:
            station_comment += (
                f"; built per piece: {len(built)} run(s), the stretches of the window in which every member "
                f"is inside one of its runs, {len(dropped)} piece(s) under {min_piece_h:g} h left out "
                f"({sum(b - a for a, b in dropped) / 3.6e12:.2f} h)"
            )
        if provenance is not None:
            station_comment += f"; recipe={provenance['recipe']} recipe_hash={provenance['recipe_hash']}"
        station_group.metadata.comments = station_comment
        station_group.write_metadata()

        first = last = None
        for k, (span, total, infos, used) in enumerate(built, 1):
            t0_iso, t1_iso = span.iso(0), span.iso(span.n - 1)
            run_comment, chan_comments = _weights_comments(infos, t0_iso) if infos else (None, {})
            if used is not None:
                piece = (f"piece {k} of {len(built)}, {t0_iso} to {t1_iso} ({span.n / span.fs / 3600:.2f} h), "
                         f"from the members' runs " + ", ".join(f"{s} {r}" for s, r in sorted(used.items())))
                run_comment = f"{piece}\n{run_comment}" if run_comment else piece
            if calibration_line:
                run_comment = f"{run_comment}\n{calibration_line}" if run_comment else calibration_line
            if provenance_line:
                run_comment = f"{run_comment}\n{provenance_line}" if run_comment else provenance_line
            run_group = station_group.add_run(f"sr{_rate_label(span.fs)}_{k:04d}")
            for comp in COILS:
                # the channel carries the reference member's chain, which processing removes as it does a member's
                ch = run_group.add_channel(
                    comp,
                    "magnetic",
                    total[comp].astype("float32"),
                    channel_dtype="float32",
                )
                cal = plan.get(comp)
                ch.metadata.component = comp
                ch.metadata.sample_rate = span.fs
                ch.metadata.time_period.start = t0_iso
                ch.metadata.time_period.end = t1_iso
                ch.metadata.units = cal["units"] if cal else "digital counts"
                if cal:
                    for stage, (f, applied) in enumerate(zip(cal["filters"], cal["applied"]), 1):
                        ch.metadata.add_filter(name=f.name, applied=bool(applied), stage=stage)
                ch.metadata.measurement_azimuth = 0.0 if comp == "hx" else 90.0
                if comp in chan_comments:
                    # set the Comment's value; any text holding "|" is still split on it (upstream issue 75),
                    # and the weights text holds none
                    ch.metadata.comments.value = chan_comments[comp]
                ch.write_metadata()
                total[comp] = None  # release the float64 coil once it is written
            run_group.metadata.sample_rate = span.fs
            run_group.metadata.time_period.start = t0_iso
            run_group.metadata.time_period.end = t1_iso
            if run_comment:
                run_group.metadata.comments.value = run_comment
            run_group.write_metadata()
            first = first or run_group.metadata.time_period.start
            last = run_group.metadata.time_period.end
        station_group.metadata.time_period.start = first
        station_group.metadata.time_period.end = last
        station_group.write_metadata()
    finally:
        m.close_mth5()
    logger.info(f"{name}: wrote {out_path}")
    return out_path
