# -*- coding: utf-8 -*-
"""
Inter-site transfer functions: the telluric tensor T and the horizontal magnetic tensor M

For two sites recording at the same time, the telluric tensor T maps the
base site's horizontal electric field onto the local site's,
E_local = T E_base, and the horizontal magnetic tensor M maps the base's
horizontal magnetic field onto the local's, H_local = M H_base. Both are
2 x 2 complex tensors per period, dimensionless once each channel is
calibrated (E in mV/km, H in nT). Over a polarisable body the phase of
T_eff = sqrt(det T), arg(det T) / 2, departs from the inductive value by a
few tenths of a degree to a few degrees, which makes the phase precision
the product. M departs from the identity where the two sites' coils differ
in response, gain or azimuth, or where the magnetic field itself differs.

The estimate is a native one, independent of aurora: per band of the
survey's band scheme (`mt_workbench.bands.build_band_scheme`, so T, M and
the impedances Z share their periods), the outputs (the local's ex, ey or
hx, hy) are regressed on the inputs (the base's same pair) by Huber
iteratively reweighted least squares, referenced to a third site's
channels or to a stack of several sites' channels, with errors from a
delete-one-group jackknife over time. The reference is never the base's
own channels: the base's input noise would bias the estimate low (errors
in variables), which the remote reference exists to avoid.

How it works

`read_channels` reads a site's channels from its MTH5 archive onto one
sample grid (NaN where no run covers a sample) with the response of each
channel's filter chain in each run, taken as aurora removes it (the
applied filters other than decimation and delay; `mt_workbench.crosspower`'s
reader).
`band_spectra` removes each channel's median, zeroes the gaps and walks the
band scheme's factor-4 decimation levels (`mt_workbench.timefreq`'s
zero-phase FIR cascade). On each level it takes windows of the scheme's
length (128 samples) at 25 % overlap (75 % for windows longer than
600 s), drops the windows touching a gap, keeps at most `MAX_WINDOWS`
evenly spread, first-differences each window, removes its mean, applies a
Hann taper and transforms it. Each harmonic is then divided by its
channel's chain response and by the first difference's response, so the
spectra are calibrated: a filter response that differs between two sites
is removed from each and cannot pass as a phase of T or M. A band holds the
harmonics f_lo <= f < f_hi.

A burst site's archive (one run per 24 kHz burst of a Phoenix receiver,
`bursts_of:`) is read by `read_bursts` instead: the bursts the sites share
(`burst_slots`) back to back with one NaN sample between them, a compact
grid whose memory is that of the bursts.

`estimate_band` solves each output row y = X b with weights w by the
reference R: b = (sum w R* X^T)^-1 (sum w R* y). The weights are Huber's,
w = min(1, r0 s / |r|) with r0 1.5 and s 1.4826 times the median absolute
residual, iterated up to 12 times until the solution changes by less than
1e-5 relative; ``method="ls"`` keeps w = 1, the linear estimator, with
which T = <E_l R*><E_b R*>^-1 exactly. The jackknife deletes one of 20
equal time slices of the record at a time, solving with the full fit's
weights; a slice holding no window of the band is not deleted (deleting
it would repeat the full estimate and shrink the error). The error of each
element is the jackknife standard deviation of its complex value, and the
invariants carry their own jackknife errors: |det|, arg(det) / 2 and
|T_eff| = sqrt(|det|). The estimator is the robust magnetic-tensor
estimate of the earlier coil-replacement trials, which passed a synthetic
recovery check on real noise, extended with calibration,
any channel pair as outputs, inputs and reference, the empty-slice rule
above and a recoloured first difference.

The stack

`select_stack` lists every survey site at the pair's sample rate whose
archive covers the window by at least `MIN_OVERLAP_HOURS` (or the whole
window when it is shorter) and records the channels asked for, leaving out
the local, the base and an exclude list, each with its reason. Given a
rate, it needs no local (a stack declared on its own, `mt_workbench.stacks`);
given `runs_of`, it takes each site's runs from that callable instead of
reading the archive, so the GUI can judge membership from runs it has
already read, and a site with no runs yet is left out as `NOT_READ`.

By default the stack is formed per band from the members' spectra
(`band_stack`). Each member's channels are read from its processing
archive (the filtered variant when it declares filters) with their filter
chains and go through `band_spectra` beside the pair's channels as
optional channels: the same windows, decimation and calibration as the
estimator's own channels, so members on different gains or responses are
comparable, and a member's gaps leave out only its own windows. In each
band each member channel is divided by its robust scale, the square root
of the median over windows of its band power (the mean of |x|^2 over the
band's harmonics). In each window the array level is the median over the
members present of that normalised power, and a member whose normalised
power exceeds `STACK_REJECT_FACTOR` (25) times the array level is left
out of that window: a natural event raises every member and is kept, a
member's own fault or burst is not. The stack in a window is the mean of
the kept members' normalised spectra; a window where fewer than
`STACK_MIN_MEMBERS` (2) are kept, in either channel, is left out of the
band. The rejection needs three members or more to act: with two the
median is their mean, which neither can exceed 25 times.

With ``method="median"`` (`STACK_METHODS`) the stack in a window is the
marginal median of the same kept members' normalised spectra, per
harmonic: the median of the real parts plus i times the median of the
imaginary parts, the mean of the two middle values for an even count.
Presence, scale, level and rejection are those of the mean, so the two
methods differ only in how the kept members are combined. A member far
from the others in a window that the 25x rejection keeps (a fault under
the threshold, a member against the rest) moves the median by at most
one rank, where it moves the mean in proportion. With two kept members
the median is exactly their mean, and with three it is the middle
one per part. numpy's median of complex values sorts them by real part
first and is not the marginal median, so the parts are taken apart. The
members must be calibrated alike for the median to be a field: it is not
unchanged by a common phase rotation of the members (`STACK_UNITS_MEDIAN`).

The scale is per band, not over the whole window. A member's RMS over the
window is set by its longest periods and, for E, by electrode drift and
bursts; it can swing by 20x between the halves of a day while the
member's band power does not, and a failing member's RMS is set by its
fault. The members' scales and rejected fractions per band, and the
windows each band leaves out, go into the product's sidecar.

`stack_channels` keeps the earlier plain stack (process_intersite.py's
`--stack-plain`): in the time domain each member channel loses its median,
is divided by its RMS over the window, the members present at each sample
are averaged, and the stack goes through `band_spectra` as one channel. A
failing member sets the plain stack while it fails. The plain stack's
members and RMS go into the sidecar.

The remote-reference estimate is unchanged by any fixed linear transform
of the reference, so neither stack needs units, and a mix that changes
where a member starts or stops is still a reference. Neither stack aligns
the members' signs or weights them by coherence.

The stack as the base

The band stack of the members' ex, ey can also be the inputs:
E_local = T E_stack, with a third site's H or a stack of H as the
reference. So can the band stack of the members' hx, hy, for M:
H_local = M H_stack, with a third site's H or E or a stack of either as
the reference; where the electrics are lost at nearly every site, the
magnetic stack ties every local to one regional H. The stack's field
follows the tensor (`BASE_FIELDS`): E for T, H for M. The members are
chosen as for a reference stack, the local always left out
(`select_stack` with no base), and stacked by `band_stack` with the same
scale and rejection. Being a base asks more of the stack than being a
reference does, since T or M is then the local's field on that
particular mix of the members:

- The mix must not change inside the window. A member whose record
  starts or ends inside it mixes several tensors into one T.
  `member_changes` lists each start and end of a member's runs inside
  the window, from the archives' metadata, so that a run can be refused
  or the change recorded. A start or end within `MEMBER_EDGE_S` (60 s) of
  the window's edges, or a gap between two runs shorter than that, is not
  a change: the epochs of a survey plan are cut to whole seconds, and
  consecutive files of one logger are a millisecond apart.
- A member with a reversed dipole or coil subtracts from the stack
  instead of adding to it. `polarity_screen` passes the bands through unchanged and
  records, for each band of 1-100 s (`POLARITY_PERIODS`), each member
  channel's correlation with the mean of the other members' same channel
  (`polarity_band`): each member over its per-band scale, the windows
  `stack_band` would reject left out, the correlation the real part of
  sum x conj(s) over sqrt(sum |x|^2 sum |s|^2) over the windows and
  harmonics. `polarity_summary` takes the median over the bands; a
  negative median flags the member's channel, and a member flagged in
  either channel can be left out of the stack. With two members each is
  the other's mean, so a reversal flags both; the screen needs three.
- A reference that shares a site with the base stack shares that site's
  cultural noise with the inputs, which biases the estimate as the base's
  own channels would (errors in variables). `_check_keys` refuses it
  unless told to allow it.

T on the stack is the local's T relative to the mean of that window's
members: each member enters at its per-band scale, so the stack's own
tensor is a weighted mean of the members' and changes when they do. The
members' scales per band are recorded so that the products of different
windows can be tied together afterwards.

Units on the stack. The stack's channels are in each band's normalised
units, not in mV/km or nT: in a band where the members carry one common
field F (each member g_m F plus its noise, at scale s_m), the stack's
channel r is mean_m(g_m / s_m,r) F_r, so column r of T or M on the stack
is the field ratio's column r divided by that real, positive factor. |T|
and |M| are therefore not field ratios, and neither is the ratio of two
elements in different columns. The phases are unaffected, and so are
arg(det) / 2, the delay of the timing check and the ratio of two elements
of one column. The decision is to leave the tensor in these units rather
than to rescale it by an estimate of the factor, which would put the
members' gain errors into the product; `band_stack` records each
member's scale per band and their root mean square, ``stack_scale_rms``,
so that a reader can put the tensor back to a field ratio:
column r times 1 / stack_scale_rms[r] is the ratio to a member's field
when the members are calibrated alike (all s_m,r equal); the exact
factor of the model above is mean_m(g_m / s_m,r), which the per-member
scales give when the gains are 1.

Conventions

The spectra follow numpy's forward FFT (kernel exp(-i w t)). When the
local's channels lag the base's by tau, local(t) = base(t - tau), T and M
carry a phase of -360 f tau degrees, and so does arg(det T) / 2.
`timing_check` fits that line to arg(det) / 2 over the shortest decade of
periods and reports tau in ms with its error: a clock offset between two
loggers is the first thing that mimics IP (10 ms is 3.6 deg at 1 s). A
band's estimate weights its harmonics by their cross power, so the line is
fitted at each band's frequency weighted the same way (`f_weighted`), not
at the plain mean of its harmonics, which on a red spectrum lies above it
and biases tau low. Between neighbouring short-period bands a delay of a
few ms turns arg(det) by more than 180 deg, so each band's phase goes onto
the branch nearest the best line of a scan over delays, not onto the one
nearest its neighbour.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from loguru import logger
from mth5.mth5 import MTH5
from scipy.signal import get_window

from .crosspower import _layout, _read, _roles
from .ingest import default_archive_path, processing_archive
from .masks import applies, masks_for_role, normalise
from .phoenix import warn_without_h_polarity
from .survey import Survey
from .timefreq import GAP_DILATE, _merge_intervals, decimation_levels

KINDS = {"telluric": ("ex", "ey"), "magnetic": ("hx", "hy")}  # the channels of each tensor, outputs and inputs
TENSORS = {"telluric": "T", "magnetic": "M"}
STEM_CODES = {"telluric": "te", "magnetic": "hm"}
FIELDS = {"E": ("ex", "ey"), "H": ("hx", "hy")}  # the channel pairs a reference may take
BASE_FIELDS = {"telluric": "E", "magnetic": "H"}  # the field a base stack takes for each tensor
ELEMENTS = ("xx", "xy", "yx", "yy")
METHODS = ("huber", "ls")
R0 = 1.5  # Huber threshold, in units of the residual scale
MAX_ITERATIONS = 12
TOLERANCE = 1e-5  # relative change of the solution that ends the iterations
JACKKNIFE_GROUPS = 20  # equal time slices of the record
MIN_GROUPS = 3  # slices holding a window, fewer gives no error
MAX_WINDOWS = 120_000  # windows kept per level, evenly spread
MIN_LEVEL_WINDOWS = 4  # a level with fewer windows gives no band
MIN_SAMPLES = 20  # spectral samples (windows x harmonics) a band needs
MIN_DELETED_SAMPLES = 8  # samples left after a deletion for its solution to count
FLAG_MIN_GROUPS = 5  # a band with fewer jackknife slices is flagged: its error rests on too few
# The coherence screen limit of upstream 110: a coherence of the output on the reference, not calibrated
# against the errors of T.
FLAG_COHERENCE = 0.1  # a band whose weighted output coherence (either row) is under this is flagged
LONG_WINDOW_S = 600.0  # windows longer than this overlap 75 %, the others 25 %
MIN_OVERLAP_HOURS = 12.0  # the default overlap a stack member needs with the window
STACK_REJECT_FACTOR = 25.0  # a member's window over this many times the array level leaves the band stack
STACK_MIN_MEMBERS = 2  # kept members a window of the band stack needs
STACK_METHODS = ("mean", "median")  # how the band stack combines its kept members (METHODS is the estimator's)
NOT_READ = "archive not read yet"  # select_stack's reason when its runs_of has no runs for a site yet
MEMBER_EDGE_S = 60.0  # a member's start or end this near the window's edges, or a gap this short, is no change
POLARITY_PERIODS = (1.0, 100.0)  # the bands of the polarity screen, s
TIMING_DECADES = 1.0  # the timing fit spans this many decades from the shortest period
TIMING_CHI2_WARN = 4.0  # a timing fit above this chi2/dof is printed as not a line
TIMING_CLOCK_TOLERANCE_S = 1.0  # the largest delay scanned, s; offsets of whole seconds are for scripts/timing_qc.py
TIMING_TIE_FRACTION = 0.02  # scan maxima within this fraction of the highest are near-equal: the smallest |tau| is taken
TIMING_MIN_RESULTANT = 0.97  # met by a line with 7 deg errors in arg(det) / 2, by no scan of ten noise phases in 1000
TIMING_SCAN_CHUNK = 100_000  # delays scored per block, to bound the memory of a wide scan
TIMING_TURN_FRACTION = 0.01  # residuals under this fraction of the line's turn read as a delay's own bending
RESIDUAL_SCALE = 1.4826  # median absolute residual to scale
UNITS = "dimensionless: each channel calibrated through its own filter chain (E in mV/km, H in nT)"
STACK_UNITS = ("the inputs are a band stack: column r of the tensor is in each band's normalised units, the field "
               "ratio's column divided by mean_m(g_m / s_m,r) over the members (s_m,r a member's per-band scale); "
               "the moduli and the ratio of elements in different columns are not field ratios, the phases, "
               "arg(det) / 2 and the ratio of two elements of one column are unaffected; column r times "
               "1 / stack_scale_rms[r] is the ratio to a member's field when the members are calibrated alike")
STACK_UNITS_MEDIAN = ("the inputs are a band median stack: column r of the tensor is in each band's normalised "
                      "units, the marginal median over the members of their spectra over their per-band scales "
                      "s_m,r, whose factor is not mean_m(g_m / s_m,r); the moduli and the ratio of elements in "
                      "different columns are not field ratios; the phases and arg(det) / 2 are the members' "
                      "common phase only when the members' phase responses agree, since the marginal median is "
                      "not unchanged by a common phase rotation; with two members kept the stack is their mean")


@dataclass
class BandSpectra:
    """The calibrated spectra of one band.

    Attributes:
        level (int): Decimation level of the band scheme.
        f_lo (float): Lower band edge, Hz.
        f_hi (float): Upper band edge, Hz.
        freqs (np.ndarray): The band's FFT harmonics, Hz.
        t_mid (np.ndarray): Each window's centre, s from the record's first sample.
        record_s (float): Length of the record, s.
        spectra (dict): Channel key to complex64 [windows, harmonics].
    """

    level: int
    f_lo: float
    f_hi: float
    freqs: np.ndarray
    t_mid: np.ndarray
    record_s: float
    spectra: dict

    @property
    def period(self) -> float:
        """The band's period as aurora labels it, 1 / sqrt(f_lo f_hi), s."""
        return 1.0 / math.sqrt(self.f_lo * self.f_hi)

    @property
    def f_mean(self) -> float:
        """The mean frequency of the band's harmonics, Hz."""
        return float(np.mean(self.freqs))

    @property
    def n_windows(self) -> int:
        """Windows the band holds."""
        return int(self.t_mid.size)


@dataclass
class RunResponses:
    """The chain responses of a channel whose runs hold different filter chains.

    The grid is cut into spans at the first sample of each run whose chain
    differs from the run before it; a window takes the response of the
    span holding its centre. `read_channels` marks the sample at each such
    cut as a gap, so a kept window lies in one run.

    Attributes:
        starts (np.ndarray): The first grid sample of each span, ascending,
            the first one 0.
        responses (list): Per span, a callable giving that run's chain
            response at an array of frequencies.
    """

    starts: np.ndarray
    responses: list

    def span_of(self, samples: np.ndarray) -> np.ndarray:
        """Return the span index of each grid sample position."""
        return np.maximum(np.searchsorted(self.starts, samples, side="right") - 1, 0)


def window_hop(window: int, sample_rate: float) -> int:
    """Return the hop between windows in samples: 25 % overlap, 75 % for windows longer than `LONG_WINDOW_S`."""
    return window // 4 if window / sample_rate > LONG_WINDOW_S else (window * 3) // 4


def _spans(bad: np.ndarray) -> list[tuple[int, int]]:
    """Return the [a, b) runs of True in a boolean array."""
    if not bad.any():
        return []
    step = np.diff(np.concatenate([[0], bad.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(step == 1).tolist(), np.flatnonzero(step == -1).tolist()))


def _carry_gaps(gaps: list[tuple[int, int]], factor: int, n_level: int) -> list[tuple[int, int]]:
    """Return gaps on the next decimation level, dilated as `mt_workbench.timefreq.decimation_levels` dilates them."""
    return _merge_intervals([(max(0, a // factor - GAP_DILATE), min(n_level, b // factor + 1 + GAP_DILATE))
                             for a, b in gaps])


def mask_role(role: str) -> str:
    """Return the role of `mt_workbench.masks.masks_for_role` whose scopes a site takes in an inter-site run.

    The local and the base take the masks.yaml entries of scope local or
    both, since the base's channels are inputs of the tensor as a local's
    are; the reference takes those of scope both or remote, as the remote
    of scripts/process_rr.py does.

    Args:
        role (str): "local", "base" or "reference".

    Returns:
        str: "local" or "remote".
    """
    return {"local": "local", "base": "local", "reference": "remote"}[role]


def site_masks(masks, role: str, channels) -> dict:
    """Split a site's masks.yaml entries into those an inter-site run applies and those it leaves out.

    The scope decides first (`mask_role`). An entry in scope applies when
    it names every channel or one of `channels`, the channels the run reads
    from the site, and then leaves out whole windows for every element of
    the tensor.

    Args:
        masks (iterable of dict): The site's entries (`mt_workbench.masks.load_masks`).
        role (str): "local", "base" or "reference".
        channels (tuple): The channels read from the site, e.g. ("ex", "ey").

    Returns:
        dict: "applied", "left_out_scope" and "left_out_channels", each a
        list of normalised entries in the order given.
    """
    out = {"applied": [], "left_out_scope": [], "left_out_channels": []}
    for m in (normalise(m) for m in masks or []):
        if not masks_for_role([m], mask_role(role)):
            out["left_out_scope"].append(m)
        elif m["channels"] == "all" or set(m["channels"]) & set(channels):
            out["applied"].append(m)
        else:
            out["left_out_channels"].append(m)
    return out


def mask_spans(masks, t0_ns: int, n: int, sample_rate: float, label: str, slots_ns=None,
               per_burst: int | None = None) -> list[tuple]:
    """Return the grid samples that masks cover, in the form `band_spectra` takes them.

    A sample lies in a mask when start <= its time < end. On a dense grid
    sample i is at t0_ns + i / sample_rate. On the compact grid of
    `read_bursts` burst k starts at sample k (per_burst + `BURST_GAP`), and
    its sample j is at slots_ns[k] + j / sample_rate.

    Args:
        masks (iterable of dict): masks.yaml entries.
        t0_ns (int): Time of the dense grid's first sample, ns since the epoch.
        n (int): Samples of the dense grid.
        sample_rate (float): Sample rate, Hz.
        label (str): The name the counts are kept under, the site.
        slots_ns (list of int, optional): The burst starts of a compact grid.
        per_burst (int, optional): Samples per burst of a compact grid.

    Returns:
        list of tuple: (first sample, end sample, bands, label) per span
        holding a sample, bands "all" or [pmin_s, pmax_s].
    """
    if slots_ns is None:
        offsets, origins, size = np.zeros(1, dtype=np.int64), np.array([int(t0_ns)], dtype=np.int64), int(n)
    else:
        origins = np.asarray([int(s) for s in slots_ns], dtype=np.int64)
        offsets, size = np.arange(origins.size, dtype=np.int64) * (int(per_burst) + BURST_GAP), int(per_burst)

    def first_at(t_ns: int) -> np.ndarray:
        # the first sample at or after t_ns of each piece, held to [0, size]
        return np.clip(np.ceil((t_ns - origins) / 1e9 * sample_rate - 1e-6), 0, size).astype(np.int64)

    out = []
    for m in (normalise(m) for m in masks or []):
        a, b = first_at(_ns(m["start"])), first_at(_ns(m["end"]))
        for k in np.flatnonzero(b > a):
            out.append((int(offsets[k] + a[k]), int(offsets[k] + b[k]), m["bands"], label))
    return out


def _mask_groups(masked) -> list[tuple]:
    """Merge mask spans by (label, bands); return (label, bands, starts, ends), the spans sorted and disjoint."""
    groups: dict = {}
    for a, b, bands, label in masked:
        key = (label, "all" if bands == "all" else (float(bands[0]), float(bands[1])))
        groups.setdefault(key, []).append((int(a), int(b)))
    out = []
    for (label, bands), spans in groups.items():
        merged = _merge_intervals(spans)
        out.append((label, bands, np.array([a for a, _b in merged], dtype=np.int64),
                    np.array([b for _a, b in merged], dtype=np.int64)))
    return out


def _overlaps(starts: np.ndarray, ends: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Flag each [lo, hi) that overlaps one of the sorted disjoint spans [starts, ends)."""
    j = np.searchsorted(ends, lo, side="right")  # the first span ending after lo
    out = np.zeros(lo.size, dtype=bool)
    ok = j < ends.size
    out[ok] = starts[j[ok]] < hi[ok]
    return out


def band_spectra(arrays: dict, sample_rate: float, band_scheme: dict, responses: dict | None = None,
                 max_windows: int = MAX_WINDOWS, optional=(), masked=None, mask_record: list | None = None):
    """Yield the calibrated spectra of every band of a band scheme.

    A sample is a gap when any channel is NaN there. `arrays` is consumed:
    each channel loses its median, the gaps are zeroed and each level of
    the decimation cascade replaces the one before it (see How it works
    in the module docstring).

    The `optional` channels (a stack's members) do not make gaps: each
    loses the median of the samples it covers, its own NaN are zeroed, its
    own gaps are carried down the levels and dilated as the shared ones
    are, and a window touching one of them gives NaN spectra for that
    channel alone. The windows are chosen from the other channels' gaps
    only, so the optional channels change neither the windows nor the
    spectra of the others.

    `masked` spans (`mask_spans`) leave out every window holding a base
    sample inside one: a window of level L stands for the base samples of
    its win + 1 level samples, each standing for factor**L. A span of
    bands "all" is cut from the level's window choice before the windows
    are thinned to `max_windows`; a band-limited one from the bands whose
    period it covers (`mt_workbench.masks.applies`). A level or band left
    with fewer than `MIN_LEVEL_WINDOWS` windows is not formed.

    Args:
        arrays (dict): Channel key to samples on one grid (float32 is kept
            as it is, anything else is converted), NaN in gaps.
        sample_rate (float): Sample rate of the arrays, Hz.
        band_scheme (dict): The survey's band scheme (`mt_workbench.bands.build_band_scheme`).
        responses (dict, optional): Channel key to a callable giving the
            complex response of its filter chain at an array of
            frequencies, or a `RunResponses` when its runs hold different
            chains; a key without one is left as it is.
        max_windows (int): Windows kept per level, evenly spread.
        optional (iterable of str): Channel keys whose gaps are their own
            (above); at least one channel must not be optional.
        masked (list of tuple, optional): (first sample, end sample,
            bands, label) spans on the arrays' grid, from `mask_spans`.
        mask_record (list, optional): Gets one dict per band with
            harmonics on a level of at least `MIN_LEVEL_WINDOWS` windows
            before the masks: "level", "period_s", "windows" (the level's
            windows clear of gaps, before the masks and the thinning),
            "masked" ({label: those windows a label's spans cover}) and
            "left_out" (those any span covers).

    Yields:
        BandSpectra: One per band holding a harmonic, level by level.

    Raises:
        ValueError: When the arrays differ in length, an optional key is
            not a channel, every channel is optional, or no sample is
            covered by every channel that is not optional.
    """
    keys = tuple(arrays)
    optional = tuple(optional or ())
    unknown = sorted(set(optional) - set(keys))
    if unknown:
        raise ValueError(f"optional channels {unknown} are not among the arrays")
    if len(set(optional)) == len(keys):
        raise ValueError("every channel is optional: the windows need one that is not")
    n0 = int(np.asarray(arrays[keys[0]]).size)
    bad = np.zeros(n0, dtype=bool)
    own_gaps = {}
    for key in keys:
        a = np.asarray(arrays[key], dtype=np.float32)
        if a.size != n0:
            raise ValueError(f"{key}: {a.size} samples, {keys[0]} has {n0}")
        arrays[key] = a
        if key in optional:
            own_gaps[key] = _spans(~np.isfinite(a))
        else:
            bad |= ~np.isfinite(a)
    if bad.all():
        raise ValueError("no sample is covered by every channel")
    step = max(1, n0 // 1_000_000)
    for key in keys:
        sub = arrays[key][::step]
        if key in own_gaps:
            sub = sub[np.isfinite(sub)]
            if sub.size:
                arrays[key] -= np.float32(np.median(sub))
            for a, b in own_gaps[key]:
                arrays[key][a:b] = 0.0
            continue
        sub = sub[~bad[::step]]
        arrays[key] -= np.float32(np.median(sub))
    gaps = _spans(bad)
    del bad
    record_s = n0 / float(sample_rate)
    factors = list(band_scheme["decimation_factors"])
    factor = int(factors[1]) if len(factors) > 1 else 4
    windows = [int(w) for w in band_scheme["num_samples_window"]]
    edges_by_level = band_scheme["band_edges"]
    responses = responses or {}
    groups = _mask_groups(masked) if masked else []
    for level, fs, level_gaps in decimation_levels(arrays, gaps, sample_rate, len(windows), keys, factor):
        if level > 0:
            n_level = arrays[keys[0]].size
            own_gaps = {key: _carry_gaps(g, factor, n_level) for key, g in own_gaps.items()}
        edges = np.asarray(edges_by_level.get(level, []), dtype=float).reshape(-1, 2)
        if edges.size == 0:
            continue
        win, scale = windows[level], factor**level
        n = arrays[keys[0]].size
        if n < win + 2:
            continue
        starts = np.arange(0, n - win - 1, window_hop(win, fs))
        if level_gaps:
            gap = np.zeros(n, dtype=bool)
            for a, b in level_gaps:
                gap[a:b] = True
            cum = np.concatenate([[0], np.cumsum(gap)])
            starts = starts[(cum[starts + win + 1] - cum[starts]) == 0]
        if groups:
            # each window's base samples [lo, hi); hits on the windows clear of gaps, before the thinning
            hits = [(label, bands, _overlaps(a, b, starts * scale, (starts + win + 1) * scale))
                    for label, bands, a, b in groups]
            if mask_record is not None and starts.size >= MIN_LEVEL_WINDOWS:
                level_freqs = np.fft.rfftfreq(win, 1.0 / fs)
                for lo, hi in edges:
                    if not np.any((level_freqs >= lo) & (level_freqs < hi)):
                        continue
                    period = 1.0 / math.sqrt(lo * hi)
                    cover: dict = {}
                    for label, bands, hit in hits:
                        if bands == "all" or applies({"bands": bands}, period):
                            cover[label] = cover.get(label, np.zeros(starts.size, dtype=bool)) | hit
                    left = np.logical_or.reduce(list(cover.values())) if cover else np.zeros(starts.size, bool)
                    mask_record.append({"level": int(level), "period_s": period, "windows": int(starts.size),
                                        "masked": {label: int(h.sum()) for label, h in cover.items()},
                                        "left_out": int(left.sum())})
            whole = [hit for _label, bands, hit in hits if bands == "all"]
            kept = np.flatnonzero(~np.logical_or.reduce(whole)) if whole else np.arange(starts.size)
            starts = starts[kept]
        if starts.size > max_windows:
            pick = np.linspace(0, starts.size - 1, max_windows).astype(int)
            starts = starts[pick]
            if groups:
                kept = kept[pick]
        if starts.size < MIN_LEVEL_WINDOWS:
            continue
        freqs = np.fft.rfftfreq(win, 1.0 / fs)
        members = [(lo, hi, np.flatnonzero((freqs >= lo) & (freqs < hi))) for lo, hi in edges]
        cols = np.unique(np.concatenate([k for _lo, _hi, k in members]))
        if cols.size == 0:
            continue
        # the first difference multiplies each harmonic by exp(2 pi i f / fs) - 1; it is divided out
        recolour = np.exp(2j * np.pi * freqs[cols] / fs) - 1.0
        taper = get_window("hann", win)
        index = starts[:, None] + np.arange(win + 1)[None, :]
        ffts = {}
        for key in keys:
            seg = np.diff(arrays[key][index], axis=1)
            seg -= seg.mean(axis=1, keepdims=True)
            resp = responses.get(key)
            if isinstance(resp, RunResponses):
                # each window divided by the chain of the run holding its centre, in base samples
                span = resp.span_of((starts + win / 2.0) * scale)
                divisor = np.empty((starts.size, cols.size), dtype=complex)
                for j in np.unique(span):
                    divisor[span == j] = recolour * np.asarray(resp.responses[j](freqs[cols]), dtype=complex)
            else:
                divisor = recolour * (np.asarray(resp(freqs[cols]), dtype=complex) if resp is not None else 1.0)
            ffts[key] = (np.fft.rfft(seg * taper, axis=1)[:, cols] / divisor).astype(np.complex64)
            del seg
            if own_gaps.get(key):
                gap = np.zeros(n, dtype=bool)
                for a, b in own_gaps[key]:
                    gap[a:b] = True
                cum = np.concatenate([[0], np.cumsum(gap)])
                ffts[key][(cum[starts + win + 1] - cum[starts]) > 0] = np.nan
                del gap, cum
        del index
        t_mid = (starts + win / 2.0) * scale / float(sample_rate)
        for lo, hi, k in members:
            if k.size == 0:
                continue
            pos = np.searchsorted(cols, k)
            period = 1.0 / math.sqrt(lo * hi)
            limited = [hit[kept] for _label, bands, hit in hits
                       if bands != "all" and applies({"bands": bands}, period)] if groups else []
            if limited:
                keep = ~np.logical_or.reduce(limited)
                if int(keep.sum()) < MIN_LEVEL_WINDOWS:
                    continue
                yield BandSpectra(level, float(lo), float(hi), freqs[k], t_mid[keep], record_s,
                                  {key: F[:, pos][keep] for key, F in ffts.items()})
                continue
            yield BandSpectra(level, float(lo), float(hi), freqs[k], t_mid, record_s,
                              {key: F[:, pos] for key, F in ffts.items()})
        del ffts


def _solve(y: np.ndarray, X: np.ndarray, R: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Return b solving sum w R* (y - X b) = 0, the weighted remote-reference normal equations."""
    Rw = np.conj(R) * w[:, None]
    return np.linalg.solve(Rw.T @ X, Rw.T @ y)


def huber_rr(y: np.ndarray, X: np.ndarray, R: np.ndarray, r0: float = R0, max_iterations: int = MAX_ITERATIONS,
             tolerance: float = TOLERANCE) -> tuple[np.ndarray, np.ndarray]:
    """Return the Huber-weighted remote-reference solution of y = X b and its final weights.

    Args:
        y (np.ndarray): Output samples [n].
        X (np.ndarray): Input samples [n, 2].
        R (np.ndarray): Reference samples [n, 2].
        r0 (float): Huber threshold in units of the residual scale.
        max_iterations (int): Reweighting steps at most.
        tolerance (float): Relative change of b that ends the iterations.

    Returns:
        tuple: (b [2] complex, w [n] weights).

    Raises:
        numpy.linalg.LinAlgError: When the normal equations are singular.
    """
    w = np.ones(y.size)
    b = _solve(y, X, R, w)
    for _ in range(max_iterations):
        r = np.abs(y - X @ b)
        s = RESIDUAL_SCALE * np.median(r) + 1e-30
        w = np.minimum(1.0, r0 * s / np.maximum(r, 1e-30))
        b_new = _solve(y, X, R, w)
        done = np.allclose(b_new, b, rtol=tolerance, atol=0)
        b = b_new
        if done:
            break
    return b, w


def _check_keys(outputs, inputs, reference, input_sites=(), reference_sites=(),
                allow_shared: bool = False) -> list[str]:
    """Refuse a reference sharing a channel with the inputs or outputs, outputs that are inputs, and shared sites.

    The channel keys are checked always. When the inputs are a stack of
    sites (the base stack), `input_sites` names its members and
    `reference_sites` the sites the reference is made of (the remote, or a
    reference stack's members); a site in both puts its own noise into the
    inputs and the reference, which is refused unless `allow_shared`. A
    stack's channel keys are its own (the stack's, not a member's), so a
    stack as the inputs beside a site or a stack as the reference passes
    the channel check.

    Args:
        outputs, inputs, reference (tuple): Two channel keys each.
        input_sites (iterable of str): The base stack's members.
        reference_sites (iterable of str): The reference's sites.
        allow_shared (bool): Accept sites in both, and return them.

    Returns:
        list: The sites in both, sorted ([] when none).

    Raises:
        ValueError: Naming the shared channels, or the shared sites.
    """
    for name, keys in (("outputs", outputs), ("inputs", inputs), ("reference", reference)):
        if len(keys) != 2 or len(set(keys)) != 2:
            raise ValueError(f"{name} must be two different channels, given {list(keys)}")
    for a, b, why in ((reference, inputs, "the reference is the inputs' own channels: the input noise would bias "
                                          "the estimate low (errors in variables)"),
                      (reference, outputs, "the reference shares the outputs' channels"),
                      (outputs, inputs, "the outputs share the inputs' channels")):
        shared = sorted(set(a) & set(b))
        if shared:
            raise ValueError(f"{why}: {shared}")
    shared_sites = sorted(set(input_sites or ()) & set(reference_sites or ()))
    if shared_sites and not allow_shared:
        raise ValueError(f"the reference shares {shared_sites} with the base stack: a site's own noise in both the "
                         f"inputs and the reference would bias the estimate (errors in variables)")
    return shared_sites


def _mcoh(y: np.ndarray, X: np.ndarray) -> float:
    """Return the squared multiple coherence of y on the columns of X."""
    S = X.T @ np.conj(X)
    c = X.T @ np.conj(y)
    try:
        v = np.real(np.conj(c) @ np.linalg.solve(S, c))
    except np.linalg.LinAlgError:
        return float("nan")
    p = float(np.sum(np.abs(y) ** 2))
    return float(v / p) if p > 0 else float("nan")


def _jackknife_sd(values: np.ndarray) -> np.ndarray:
    """Return the delete-one jackknife standard deviation along axis 0 (complex values: of the modulus)."""
    g = values.shape[0]
    dev = values - values.mean(axis=0)
    return np.sqrt((g - 1) / g * np.sum(np.abs(dev) ** 2, axis=0))


def weighted_frequency(freqs: np.ndarray, X: np.ndarray, R: np.ndarray, w: np.ndarray) -> float:
    """Return a band's frequency weighted as its estimate weights the harmonics.

    The solution b = (sum w R* X^T)^-1 (sum w R* y) sums the harmonics'
    cross powers C_k = sum over windows of w R* X^T, so a phase that
    varies across the band enters it in proportion to C_k. Each harmonic
    is weighted by sqrt|det C_k|, which no fixed linear transform of the
    inputs or the reference changes from harmonic to harmonic. On a red
    spectrum this frequency lies below the plain mean of the harmonics.

    Args:
        freqs (np.ndarray): The band's harmonics, Hz [nh].
        X (np.ndarray): Input samples [windows x nh, 2], window-major as `estimate_band` stacks them.
        R (np.ndarray): Reference samples, the same shape.
        w (np.ndarray): The solution's weights [windows x nh].

    Returns:
        float: The weighted frequency, Hz; the plain mean when the weights vanish.
    """
    nh = freqs.size
    Rw = (np.conj(R) * w[:, None]).reshape(-1, nh, 2)
    C = np.einsum("wka,wkb->kab", Rw, X.reshape(-1, nh, 2))
    c = np.sqrt(np.abs(np.linalg.det(C)))
    total = float(np.sum(c))
    return float(np.sum(freqs * c) / total) if total > 0 and np.isfinite(total) else float(np.mean(freqs))


def estimate_band(band: BandSpectra, outputs, inputs, reference, method: str = "huber",
                  groups: int = JACKKNIFE_GROUPS) -> dict:
    """Estimate the 2 x 2 tensor of one band, with its jackknife errors and invariants.

    Row i of the tensor maps the inputs onto output i:
    outputs[i] = tensor[i, 0] inputs[0] + tensor[i, 1] inputs[1].

    Args:
        band (BandSpectra): The band.
        outputs (tuple): Two channel keys of `band.spectra`.
        inputs (tuple): Two channel keys.
        reference (tuple): Two channel keys, sharing none with the others.
        method (str): "huber" (robust) or "ls" (w = 1, linear).
        groups (int): Equal time slices of the record for the jackknife.

    Returns:
        dict: ``tensor`` [2, 2] complex, ``sigma`` [2, 2], ``det``,
        ``abs_det_err``, ``half_arg_deg`` (arg(det) / 2), ``half_arg_err_deg``,
        ``n_groups``, ``coh_out`` and ``coh_in`` (the squared multiple
        coherence of each output and each input on the reference, every
        sample weighted 1), ``coh_out_weighted`` (that of each output under
        its row's final weights, sqrt(w) on the output and the reference),
        ``frac_downweighted`` (each row's fraction of samples with w < 1),
        ``pseudo`` [groups, 2, 2] (the delete-one-slice estimates, None
        without enough slices), ``f_weighted`` (`weighted_frequency`, the
        mean over the rows solved). NaN where the band has too few samples
        or a singular system.

    Raises:
        ValueError: For an unknown method or a reference sharing channels
            with the inputs or outputs (`_check_keys`).
    """
    if method not in METHODS:
        raise ValueError(f"method {method!r}: one of {METHODS}")
    _check_keys(outputs, inputs, reference)
    nan2 = np.full((2, 2), np.nan + 0j)
    out = {"tensor": nan2.copy(), "sigma": np.full((2, 2), np.nan), "det": complex(np.nan, np.nan),
           "abs_det_err": np.nan, "half_arg_deg": np.nan, "half_arg_err_deg": np.nan, "n_groups": 0,
           "coh_out": np.full(2, np.nan), "coh_in": np.full(2, np.nan), "coh_out_weighted": np.full(2, np.nan),
           "frac_downweighted": np.full(2, np.nan), "pseudo": None, "f_weighted": np.nan}
    nh = band.freqs.size

    def columns(keys):
        return np.column_stack([band.spectra[k].reshape(-1) for k in keys]).astype(np.complex128)

    Y, X, R = columns(outputs), columns(inputs), columns(reference)
    if Y.shape[0] < MIN_SAMPLES:
        return out
    out["coh_out"] = np.array([_mcoh(Y[:, i], R) for i in range(2)])
    out["coh_in"] = np.array([_mcoh(X[:, i], R) for i in range(2)])
    t = np.repeat(band.t_mid, nh)
    gid = np.minimum((t / band.record_s * groups).astype(int), groups - 1)
    present = np.unique(gid)
    tensor = nan2.copy()
    pseudo = np.full((present.size, 2, 2), np.nan + 0j)
    f_rows = []
    for i in range(2):
        try:
            if method == "huber":
                b, w = huber_rr(Y[:, i], X, R)
            else:
                w = np.ones(Y.shape[0])
                b = _solve(Y[:, i], X, R, w)
        except np.linalg.LinAlgError:
            continue
        tensor[i] = b
        sw = np.sqrt(w)
        out["coh_out_weighted"][i] = _mcoh(sw * Y[:, i], sw[:, None] * R)
        out["frac_downweighted"][i] = float(np.mean(w < 1.0))
        f_rows.append(weighted_frequency(band.freqs, X, R, w))
        for j, g in enumerate(present):
            keep = gid != g
            if keep.sum() < MIN_DELETED_SAMPLES:
                continue
            try:
                pseudo[j, i] = _solve(Y[keep, i], X[keep], R[keep], w[keep])
            except np.linalg.LinAlgError:
                pass
    out["tensor"] = tensor
    f_rows = [f for f in f_rows if np.isfinite(f)]
    out["f_weighted"] = float(np.mean(f_rows)) if f_rows else np.nan
    det = tensor[0, 0] * tensor[1, 1] - tensor[0, 1] * tensor[1, 0]
    out["det"] = complex(det)
    if np.isfinite(det):
        out["half_arg_deg"] = math.degrees(np.angle(det)) / 2.0
    pseudo = pseudo[np.all(np.isfinite(pseudo), axis=(1, 2))]
    out["n_groups"] = int(pseudo.shape[0])
    if pseudo.shape[0] >= MIN_GROUPS and np.isfinite(det) and det != 0:
        out["pseudo"] = pseudo
        out["sigma"] = _jackknife_sd(pseudo)
        dets = pseudo[:, 0, 0] * pseudo[:, 1, 1] - pseudo[:, 0, 1] * pseudo[:, 1, 0]
        out["abs_det_err"] = float(_jackknife_sd(np.abs(dets)))
        # each slice's half phase about the full estimate's, so no wrap enters
        out["half_arg_err_deg"] = math.degrees(float(_jackknife_sd(np.angle(dets / det) / 2.0)))
    return out


@dataclass
class TensorEstimate:
    """A 2 x 2 inter-site tensor per band, shortest period first.

    Attributes:
        period (np.ndarray): Band period, 1 / sqrt(f_lo f_hi), s.
        f_lo, f_hi (np.ndarray): Band edges, Hz.
        f_mean (np.ndarray): Mean frequency of the band's harmonics, Hz.
        f_weighted (np.ndarray): The band's frequency weighted by the
            cross power of its harmonics (`weighted_frequency`), Hz; the
            frequency of the timing fit.
        level (np.ndarray): Decimation level.
        n_windows, n_harm, n_groups (np.ndarray): Windows, harmonics and
            jackknife slices of each band.
        tensor (np.ndarray): [bands, 2, 2] complex.
        sigma (np.ndarray): [bands, 2, 2] jackknife errors.
        det (np.ndarray): det of the tensor, complex.
        abs_det_err (np.ndarray): Error of |det|.
        half_arg_deg, half_arg_err_deg (np.ndarray): arg(det) / 2 and its error, deg.
        coh_out, coh_in (np.ndarray): [bands, 2] squared multiple coherence
            of each output and input with the reference, every sample
            weighted 1 (the CSV's ``coh_out_unweighted_*`` and
            ``coh_in_unweighted_*``).
        coh_out_weighted (np.ndarray): [bands, 2] that of each output under
            its row's final Huber weights; NaN where not estimated (and in
            products written before it was added).
        frac_downweighted (np.ndarray): [bands, 2] each row's fraction of
            samples with a weight under 1; NaN as above.
    """

    period: np.ndarray
    f_lo: np.ndarray
    f_hi: np.ndarray
    f_mean: np.ndarray
    f_weighted: np.ndarray
    level: np.ndarray
    n_windows: np.ndarray
    n_harm: np.ndarray
    n_groups: np.ndarray
    tensor: np.ndarray
    sigma: np.ndarray
    det: np.ndarray
    abs_det_err: np.ndarray
    half_arg_deg: np.ndarray
    half_arg_err_deg: np.ndarray
    coh_out: np.ndarray
    coh_in: np.ndarray
    coh_out_weighted: np.ndarray | None = None
    frac_downweighted: np.ndarray | None = None

    def __post_init__(self):
        """Fill the columns an earlier product lacks with NaN, one row per band."""
        for name in ("coh_out_weighted", "frac_downweighted"):
            if getattr(self, name) is None:
                setattr(self, name, np.full((np.asarray(self.period).size, 2), np.nan))

    @property
    def abs_teff(self) -> np.ndarray:
        """|T_eff| = sqrt(|det|)."""
        return np.sqrt(np.abs(self.det))

    @property
    def max_abs_minus_identity(self) -> np.ndarray:
        """The largest modulus among the elements of the tensor minus the identity, per band."""
        return np.max(np.abs(self.tensor - np.eye(2)[None]), axis=(1, 2))

    def flags(self) -> dict:
        """Return the per-band flags, each a bool array; a flag marks a band and never removes it.

        - flag_not_estimated: an element of the tensor is not finite (a
          band of the layout the record could not form has 0 windows).
        - flag_few_groups: fewer than `FLAG_MIN_GROUPS` jackknife slices.
        - flag_low_coherence: the weighted coherence of either output is
          under `FLAG_COHERENCE`.
        - flag_off_diagonal: |T_xy T_yx| > |T_xx T_yy|, the tensor's shape
          when the electric channels of one site are exchanged, or a turn
          of more than 45 deg between the two sites' layouts (see the
          sidecar's frames block).
        - flag_re_det_negative: Re det < 0. An exchange makes it negative;
          so does an arg(det) / 2 beyond 45 deg with a diagonal tensor.

        The other four flags mark estimated bands only and are False on a
        band that is not estimated, which has no tensor to judge.
        """
        t = self.tensor
        est = np.all(np.isfinite(t), axis=(1, 2))
        with np.errstate(invalid="ignore"):
            low = np.any(self.coh_out_weighted < FLAG_COHERENCE, axis=1)
            off = np.abs(t[:, 0, 1] * t[:, 1, 0]) > np.abs(t[:, 0, 0] * t[:, 1, 1])
            negative = self.det.real < 0
        return {"flag_not_estimated": ~est,
                "flag_few_groups": est & (np.asarray(self.n_groups) < FLAG_MIN_GROUPS),
                "flag_low_coherence": est & low, "flag_off_diagonal": est & off,
                "flag_re_det_negative": est & negative}

    def frame(self, letter: str) -> pd.DataFrame:
        """Return the estimate as one row per band, the columns of the CSV product.

        Args:
            letter (str): The tensor's letter ("T" or "M"), the prefix of
                the element columns.

        Returns:
            pandas.DataFrame: period, f_lo, f_hi, f_mean, f_weighted, level, n_windows,
            n_harm, n_groups; ``<letter>_<el>_re``, ``_im`` and ``_err`` for
            xx, xy, yx, yy; det_re, det_im, abs_det, abs_det_err,
            half_arg_det_deg, half_arg_det_err_deg, abs_teff,
            max_abs_minus_identity; coh_out_unweighted_x, _y,
            coh_in_unweighted_x, _y, coh_out_weighted_x, _y,
            frac_downweighted_x, _y; the flags of `flags`.
        """
        cols = {"period": self.period, "f_lo": self.f_lo, "f_hi": self.f_hi, "f_mean": self.f_mean,
                "f_weighted": self.f_weighted, "level": self.level, "n_windows": self.n_windows,
                "n_harm": self.n_harm, "n_groups": self.n_groups}
        for k, el in enumerate(ELEMENTS):
            i, j = divmod(k, 2)
            cols[f"{letter}_{el}_re"] = self.tensor[:, i, j].real
            cols[f"{letter}_{el}_im"] = self.tensor[:, i, j].imag
            cols[f"{letter}_{el}_err"] = self.sigma[:, i, j]
        cols.update({"det_re": self.det.real, "det_im": self.det.imag, "abs_det": np.abs(self.det),
                     "abs_det_err": self.abs_det_err, "half_arg_det_deg": self.half_arg_deg,
                     "half_arg_det_err_deg": self.half_arg_err_deg, "abs_teff": self.abs_teff,
                     "max_abs_minus_identity": self.max_abs_minus_identity,
                     "coh_out_unweighted_x": self.coh_out[:, 0], "coh_out_unweighted_y": self.coh_out[:, 1],
                     "coh_in_unweighted_x": self.coh_in[:, 0], "coh_in_unweighted_y": self.coh_in[:, 1],
                     "coh_out_weighted_x": self.coh_out_weighted[:, 0],
                     "coh_out_weighted_y": self.coh_out_weighted[:, 1],
                     "frac_downweighted_x": self.frac_downweighted[:, 0],
                     "frac_downweighted_y": self.frac_downweighted[:, 1]})
        cols.update(self.flags())
        return pd.DataFrame(cols)

    @classmethod
    def from_frame(cls, df: pd.DataFrame) -> tuple["TensorEstimate", str]:
        """Rebuild an estimate from the frame `frame` returns (or its CSV read back).

        A frame without f_weighted (written before it was added) takes
        f_mean in its place. A frame with the earlier coherence names
        (coh_out_x ... coh_in_y, every sample weighted 1) gives them as the
        unweighted coherences, and NaN for the weighted ones.

        Returns:
            tuple: (TensorEstimate, the tensor's letter).

        Raises:
            ValueError: When the frame has no element columns.
        """
        letters = sorted({c.split("_", 1)[0] for c in df.columns if c.endswith("_xx_re")})
        if len(letters) != 1:
            raise ValueError(f"expected one tensor's element columns, found {letters}")
        letter = letters[0]
        n = len(df)
        tensor = np.empty((n, 2, 2), dtype=complex)
        sigma = np.empty((n, 2, 2))
        for k, el in enumerate(ELEMENTS):
            i, j = divmod(k, 2)
            tensor[:, i, j] = df[f"{letter}_{el}_re"].to_numpy() + 1j * df[f"{letter}_{el}_im"].to_numpy()
            sigma[:, i, j] = df[f"{letter}_{el}_err"].to_numpy()
        col = lambda name: df[name].to_numpy()  # noqa: E731
        f_weighted = col("f_weighted") if "f_weighted" in df.columns else col("f_mean")
        tag = "_unweighted" if "coh_out_unweighted_x" in df.columns else ""
        pair = lambda name: (np.column_stack([col(f"{name}_x"), col(f"{name}_y")])  # noqa: E731
                             if f"{name}_x" in df.columns else None)
        est = cls(col("period"), col("f_lo"), col("f_hi"), col("f_mean"), f_weighted, col("level").astype(int),
                  col("n_windows").astype(int), col("n_harm").astype(int), col("n_groups").astype(int),
                  tensor, sigma, col("det_re") + 1j * col("det_im"), col("abs_det_err"),
                  col("half_arg_det_deg"), col("half_arg_det_err_deg"),
                  pair(f"coh_out{tag}"), pair(f"coh_in{tag}"), pair("coh_out_weighted"), pair("frac_downweighted"))
        return est, letter


def estimate(bands, outputs, inputs, reference, method: str = "huber", groups: int = JACKKNIFE_GROUPS,
             progress=None, layout: dict | None = None) -> TensorEstimate:
    """Estimate the tensor in every band.

    With `layout`, every band of the band scheme is a row: a band that
    `band_spectra` or `band_stack` could not form (too few windows on its
    level, or none of its harmonics) is a row of NaN with 0 windows, so
    products of one survey hold the same periods.

    Args:
        bands: BandSpectra, a list or the `band_spectra` generator.
        outputs, inputs, reference (tuple): Two channel keys each (`estimate_band`).
        method (str): "huber" or "ls".
        groups (int): Jackknife time slices.
        progress: Optional callable progress(band, result), called per band.
        layout (dict, optional): The band scheme the bands were made with
            (`mt_workbench.bands.build_band_scheme`).

    Returns:
        TensorEstimate: Sorted by period, shortest first.

    Raises:
        ValueError: As `estimate_band`; or when no band is given.
    """
    _check_keys(outputs, inputs, reference)
    rows = []
    for band in bands:
        res = estimate_band(band, outputs, inputs, reference, method, groups)
        rows.append((band.period, band.f_lo, band.f_hi, band.f_mean, band.level, band.n_windows,
                     band.freqs.size, res))
        if progress is not None:
            progress(band, res)
    if not rows:
        raise ValueError("no band holds enough windows")
    if layout is not None:
        formed = [(r[4], r[1], r[2]) for r in rows]
        keys = tuple(outputs) + tuple(inputs) + tuple(reference)
        n_levels = len(layout["num_samples_window"])
        for level, edges in layout["band_edges"].items():
            if int(level) >= n_levels:
                continue
            for lo, hi in np.asarray(edges, dtype=float).reshape(-1, 2):
                if any(lv == int(level) and math.isclose(a, lo, rel_tol=1e-9) and math.isclose(b, hi, rel_tol=1e-9)
                       for lv, a, b in formed):
                    continue
                empty = BandSpectra(int(level), float(lo), float(hi), np.zeros(0), np.zeros(0), 0.0,
                                    {k: np.zeros((0, 0), dtype=np.complex64) for k in keys})
                res = estimate_band(empty, outputs, inputs, reference, method, groups)
                res["tensor"] = np.full((2, 2), complex(np.nan, np.nan))  # NaN in the imaginary parts too
                rows.append((empty.period, empty.f_lo, empty.f_hi, np.nan, empty.level, 0, 0, res))
    rows.sort(key=lambda r: r[0])
    res = [r[7] for r in rows]
    arr = lambda k, dtype=float: np.array([r[k] for r in rows], dtype=dtype)  # noqa: E731
    return TensorEstimate(
        period=arr(0), f_lo=arr(1), f_hi=arr(2), f_mean=arr(3),
        f_weighted=np.array([r["f_weighted"] for r in res], dtype=float), level=arr(4, int), n_windows=arr(5, int),
        n_harm=arr(6, int), n_groups=np.array([r["n_groups"] for r in res], dtype=int),
        tensor=np.array([r["tensor"] for r in res]), sigma=np.array([r["sigma"] for r in res]),
        det=np.array([r["det"] for r in res], dtype=complex),
        abs_det_err=np.array([r["abs_det_err"] for r in res], dtype=float),
        half_arg_deg=np.array([r["half_arg_deg"] for r in res], dtype=float),
        half_arg_err_deg=np.array([r["half_arg_err_deg"] for r in res], dtype=float),
        coh_out=np.array([r["coh_out"] for r in res]), coh_in=np.array([r["coh_in"] for r in res]),
        coh_out_weighted=np.array([r["coh_out_weighted"] for r in res]),
        frac_downweighted=np.array([r["frac_downweighted"] for r in res]))


def _line_fit(x: np.ndarray, y: np.ndarray, sd: np.ndarray) -> dict:
    """Weighted least-squares line y = a + b x; the errors scaled up by sqrt(chi2 / dof) when that exceeds 1."""
    w = 1.0 / sd**2
    A = np.column_stack([np.ones_like(x), x])
    cov = np.linalg.inv(A.T @ (A * w[:, None]))
    a, b = cov @ (A.T @ (w * y))
    dof = x.size - 2
    chi2 = float(np.sum(w * (y - a - b * x) ** 2) / dof) if dof > 0 else float("nan")
    scale = math.sqrt(max(1.0, chi2)) if np.isfinite(chi2) else 1.0
    return {"a": float(a), "b": float(b), "a_err": float(math.sqrt(cov[0, 0]) * scale),
            "b_err": float(math.sqrt(cov[1, 1]) * scale), "chi2_red": chi2}


def _resultant(f: np.ndarray, phase_deg: np.ndarray, w: np.ndarray, k: float, taus: np.ndarray) -> np.ndarray:
    """Return sum w exp(i k (phase + 360 f tau)) at each tau, in blocks of `TIMING_SCAN_CHUNK` delays."""
    out = np.empty(taus.size, complex)
    for s in range(0, taus.size, TIMING_SCAN_CHUNK):
        t = taus[s:s + TIMING_SCAN_CHUNK]
        out[s:s + t.size] = np.exp(1j * k * (phase_deg[None, :] + 360.0 * f[None, :] * t[:, None])) @ w
    return out


def _unwrap_to_delay(f: np.ndarray, phase_deg: np.ndarray, sd_deg: np.ndarray, cycle: float,
                     tolerance_s: float = TIMING_CLOCK_TOLERANCE_S) -> tuple[np.ndarray | None, dict]:
    """Place each band's phase on the branch nearest the best delay line found by a bounded scan.

    Each phase is known modulo `cycle`. Delays are scored by the weighted
    circular resultant R = |sum w exp(2 pi i (phase + 360 f tau) / cycle)|
    / sum w (w = 1 / sd^2), in steps that turn the phase at the highest
    frequency by 1 deg. The scan runs to +-`tolerance_s`, and to half the
    alias period when that is shorter: the first delay at which the bands'
    own pattern (R of zero phases) returns within `TIMING_TIE_FRACTION` of
    1, beyond which a delay and its alias give the same phases. Among the
    scan's local maxima within `TIMING_TIE_FRACTION` of the highest, the
    one of smallest |tau| is taken, and each phase goes onto the branch
    nearest its line. This follows a delay whose turn between neighbouring
    bands exceeds half a cycle, which `np.unwrap` cannot.

    The delay is not determined when the maximum taken lies at the scan's
    bound (the line's peak lies beyond it), when its R is under
    `TIMING_MIN_RESULTANT` (the phases are not a line), or when R expected
    of a true line with the stated errors, sum w exp(-(k sd)^2 / 2) / sum w,
    is under it (the errors are too large to place the branches).

    Args:
        f (np.ndarray): Frequencies, Hz.
        phase_deg (np.ndarray): Phases, deg, each known modulo `cycle`.
        sd_deg (np.ndarray): Their errors, deg.
        cycle (float): The period of the ambiguity, deg (180 for arg(det) / 2, 360 for an element).
        tolerance_s (float): The largest |tau| scanned, s.

    Returns:
        tuple: The phases on their branches (None when not determined), and
        a dict of ``tau_scan_s``, ``resultant``, ``resultant_expected``,
        ``alias_period_s`` (None when beyond the tolerance),
        ``scan_half_width_s``, ``determined`` and ``not_determined`` (the
        reason, or None).
    """
    k = 2.0 * np.pi / cycle
    w = 1.0 / sd_deg**2
    total = float(w.sum())
    step = 1.0 / (360.0 * float(f.max()))
    pattern = np.abs(_resultant(f, np.zeros_like(f), w, k, step * np.arange(int(math.ceil(tolerance_s / step)) + 1)))
    pattern /= total
    alias = None
    low = np.flatnonzero(pattern < 1.0 - TIMING_TIE_FRACTION)
    if low.size:
        back = np.flatnonzero(pattern[low[0]:] >= 1.0 - TIMING_TIE_FRACTION)
        if back.size:
            i = low[0] + back[0]
            while i + 1 < pattern.size and pattern[i + 1] > pattern[i]:  # on to the top of the returning lobe
                i += 1
            alias = float(step * i)
    half = tolerance_s if alias is None else min(tolerance_s, alias / 2.0)
    m = int(math.ceil(half / step))
    taus = step * np.arange(-m, m + 1)
    sums = _resultant(f, phase_deg, w, k, taus)
    r = np.abs(sums) / total
    peaks = np.flatnonzero(np.r_[True, r[1:] >= r[:-1]] & np.r_[r[:-1] >= r[1:], True])
    near = peaks[r[peaks] >= (1.0 - TIMING_TIE_FRACTION) * r[peaks].max()]
    best = int(near[np.argmin(np.abs(taus[near]))])
    expected = float(np.sum(w * np.exp(-0.5 * (k * sd_deg) ** 2)) / total)
    reason = None
    if best in (0, taus.size - 1):
        reason = (f"the best line lies at the bound of the scan (+-{step * m:.4g} s); an offset of whole seconds "
                  "is read with scripts/timing_qc.py")
    elif r[best] < TIMING_MIN_RESULTANT:
        reason = f"resultant {r[best]:.3f} under {TIMING_MIN_RESULTANT:g}: the phases are not a line"
    elif expected < TIMING_MIN_RESULTANT:
        reason = (f"the band errors allow a resultant of {expected:.3f} at most, under {TIMING_MIN_RESULTANT:g}: "
                  f"too large to place the phases on their branches")
    scan = {"tau_scan_s": float(taus[best]), "resultant": float(r[best]), "resultant_expected": expected,
            "alias_period_s": alias, "scan_half_width_s": float(step * m), "determined": reason is None,
            "not_determined": reason}
    if reason is not None:
        return None, scan
    model = np.angle(sums[best]) / k - 360.0 * f * taus[best]
    return phase_deg + cycle * np.round((model - phase_deg) / cycle), scan


def timing_check(est: TensorEstimate, decades: float = TIMING_DECADES,
                 clock_tolerance_s: float = TIMING_CLOCK_TOLERANCE_S) -> dict:
    """Fit a phase linear in frequency at the shortest periods: the delay between the two sites' channels.

    The phase of arg(det) / 2 (and, for a delay on one row, of the
    diagonal element of that row) over the bands from the shortest period
    estimated to `decades` decades longer is placed on its branches by a
    scan of delays up to `clock_tolerance_s` and half the bands' alias
    period (`_unwrap_to_delay`: arg(det) / 2 modulo 180 deg, an element
    modulo 360 deg), and phase = a - 360 f tau is fitted by weighted least
    squares at each band's `f_weighted` (weights 1 / error^2, the errors
    scaled up by sqrt(chi2 / dof) when that exceeds 1). The intercept a is
    given on its principal branch: (-90, 90] deg for arg(det) / 2, (-180,
    180] for an element. Offsets of whole seconds are for
    scripts/timing_qc.py. When the scan finds no line (its best at the
    bound, or a resultant, observed or allowed by the band errors, under
    `TIMING_MIN_RESULTANT`), the fit's values are None, ``determined`` is
    False and ``not_determined`` gives the reason.

    A pure delay does not give chi2/dof near 1 when it is a sizeable
    fraction of the shortest window: each band averages the phase over its
    harmonics and windows, which bends the band phases off the line by a
    small fraction of the line's turn (0.04-0.2 % for 5-20 ms at 1000 Hz on
    synthetic red noise). So the check also gives the RMS of the residuals
    about the line, weighted as the fit is, sqrt(sum w r^2 / sum w) with
    w = 1 / error^2, and the line's turn over the fitted bands,
    |360 tau (f_max - f_min)|, which `timing_text` compares. The weighting
    keeps the noisiest bands from setting the RMS: on line D the two bands
    beside the 50 Hz notch, with errors of 4-17 deg, make the plain RMS
    23.6 deg against a weighted 1.7 deg. The plain RMS is given beside it.

    The rule of `timing_text` (residuals under `TIMING_TURN_FRACTION` of
    the turn) is calibrated for pure delays of 5-20 ms at 1000 Hz. At 30 ms
    the delay itself destroys the shortest bands' estimate (|det| falls to
    about 1 % of the truth) while tau stays right. On a line of 10-20 ms a
    few degrees of real phase structure fall under 1 % of the turn and
    read as a clock offset. A real offset of 10-20 ms also shows as a loss
    of |T| or |M| at the shortest periods, so look there before taking tau
    for a clock offset.

    Args:
        est (TensorEstimate): The estimate.
        decades (float): Span of the fit in decades of period.
        clock_tolerance_s (float): The largest |tau| scanned, s.

    Returns:
        dict: ``quantity``, ``n_bands``, ``period_range_s``,
        ``three_shortest`` (period, f_mean, f_weighted, arg(det)/2 and its
        error, arg of the diagonal elements, each in deg), ``tau_ms``,
        ``tau_err_ms``, ``intercept_deg``, ``intercept_err_deg``,
        ``chi2_red``, ``residual_rms_deg`` (weighted),
        ``residual_rms_plain_deg``, ``turn_deg``, ``frequency``
        (the frequency the line is fitted at), ``elements`` (the same fit on
        arg xx and arg yy), and ``sign`` stating the convention; and from
        the scan ``determined``, ``not_determined``, ``resultant``,
        ``resultant_expected``, ``alias_period_s``, ``scan_half_width_s``,
        ``median_band_err_deg`` and ``clock_tolerance_s``. The fit keys are
        None with fewer than three usable bands or when the delay is not
        determined.
    """
    ok = np.isfinite(est.half_arg_deg) & np.isfinite(est.half_arg_err_deg) & (est.half_arg_err_deg > 0)
    out = {"quantity": "arg(det) / 2", "decades": decades, "n_bands": 0, "period_range_s": None,
           "three_shortest": [], "tau_ms": None, "tau_err_ms": None, "intercept_deg": None,
           "intercept_err_deg": None, "chi2_red": None, "residual_rms_deg": None, "residual_rms_plain_deg": None,
           "turn_deg": None, "determined": None, "not_determined": None, "resultant": None,
           "resultant_expected": None, "alias_period_s": None, "scan_half_width_s": None,
           "median_band_err_deg": None, "clock_tolerance_s": clock_tolerance_s,
           "frequency": "f_weighted: each band's harmonics weighted by their cross power",
           "elements": {},
           "sign": "phase = a - 360 f tau: tau > 0 when the local's channels lag the base's, "
                   "local(t) = base(t - tau)"}
    if not ok.any():
        return out
    freq = np.where(np.isfinite(est.f_weighted), est.f_weighted, est.f_mean)
    p_min = float(est.period[ok].min())
    sel = np.flatnonzero(ok & (est.period <= p_min * 10.0**decades * (1 + 1e-9)))
    sel = sel[np.argsort(freq[sel])]  # lowest frequency first
    for k in np.argsort(est.period[sel])[:3]:
        b = sel[k]
        out["three_shortest"].append({
            "period_s": float(est.period[b]), "f_mean_hz": float(est.f_mean[b]), "f_weighted_hz": float(freq[b]),
            "half_arg_det_deg": float(est.half_arg_deg[b]), "half_arg_det_err_deg": float(est.half_arg_err_deg[b]),
            "arg_xx_deg": float(np.degrees(np.angle(est.tensor[b, 0, 0]))),
            "arg_yy_deg": float(np.degrees(np.angle(est.tensor[b, 1, 1])))})
    out["n_bands"] = int(sel.size)
    out["period_range_s"] = [float(est.period[sel].min()), float(est.period[sel].max())]

    def fit(phase_deg, sd_deg, cycle):
        """Place the phases on their branches (modulo `cycle`) and fit; the intercept on its principal branch."""
        good = np.isfinite(phase_deg) & np.isfinite(sd_deg) & (sd_deg > 0)
        if good.sum() < 3:
            return None
        f = freq[sel][good]
        ph, scan = _unwrap_to_delay(f, phase_deg[good], sd_deg[good], cycle, clock_tolerance_s)
        scan = {k: v for k, v in scan.items() if k != "tau_scan_s"}
        scan["median_band_err_deg"] = float(np.median(sd_deg[good]))
        if ph is None:  # None, not NaN: the sidecar is strict JSON
            return {"tau_ms": None, "tau_err_ms": None, "intercept_deg": None, "intercept_err_deg": None,
                    "chi2_red": None, "residual_rms_deg": None, "residual_rms_plain_deg": None, "turn_deg": None,
                    "n_bands": int(good.sum()), **scan}
        res = _line_fit(f, ph, sd_deg[good])
        a = res["a"] - cycle * np.ceil(res["a"] / cycle - 0.5)
        resid = ph - res["a"] - res["b"] * f
        w = 1.0 / sd_deg[good] ** 2
        return {"tau_ms": -res["b"] / 360.0 * 1e3, "tau_err_ms": res["b_err"] / 360.0 * 1e3,
                "intercept_deg": float(a), "intercept_err_deg": res["a_err"], "chi2_red": res["chi2_red"],
                "residual_rms_deg": float(np.sqrt(np.sum(w * resid**2) / np.sum(w))),
                "residual_rms_plain_deg": float(np.sqrt(np.mean(resid**2))),
                "turn_deg": float(abs(res["b"]) * (f.max() - f.min())), "n_bands": int(good.sum()), **scan}

    main = fit(est.half_arg_deg[sel], est.half_arg_err_deg[sel], 180.0)
    if main is not None:
        out.update({k: main[k] for k in ("tau_ms", "tau_err_ms", "intercept_deg", "intercept_err_deg",
                                         "chi2_red", "residual_rms_deg", "residual_rms_plain_deg", "turn_deg",
                                         "determined", "not_determined", "resultant", "resultant_expected",
                                         "alias_period_s", "scan_half_width_s", "median_band_err_deg")})
    for name, (i, j) in (("xx", (0, 0)), ("yy", (1, 1))):
        z = est.tensor[sel, i, j]
        sd = np.degrees(est.sigma[sel, i, j] / np.abs(z))
        out["elements"][name] = fit(np.degrees(np.angle(z)), sd, 360.0)
    return out


def timing_text(check: dict) -> list[str]:
    """Return the timing check as printable lines, with a note when chi2/dof exceeds `TIMING_CHI2_WARN`.

    Above `TIMING_CHI2_WARN` the note depends on the residuals' RMS
    (weighted by 1 / error^2, ``residual_rms_deg``) against the line's
    turn: under `TIMING_TURN_FRACTION` of it the line accounts for the
    phase, and the residuals are of the size a delay of that turn leaves
    through each band's averaging, so tau reads as a clock offset; over it
    the phase is not a line in frequency, and tau is not a clock offset
    alone.
    """
    lines = []
    for row in check.get("three_shortest") or []:
        lines.append(f"timing: {row['period_s']:.4g} s ({row.get('f_weighted_hz', row['f_mean_hz']):.4g} Hz): "
                     f"arg(det)/2 {row['half_arg_det_deg']:+.3f} +/- {row['half_arg_det_err_deg']:.3f} deg, "
                     f"arg xx {row['arg_xx_deg']:+.3f}, arg yy {row['arg_yy_deg']:+.3f} deg")
    if check.get("determined") is False:
        pr = check["period_range_s"]
        lines.append(f"timing: delay not determined over {check['n_bands']} bands {pr[0]:.4g}-{pr[1]:.4g} s: "
                     f"{check['not_determined']} (median band error {check['median_band_err_deg']:.3g} deg)")
    elif check.get("tau_ms") is None:
        lines.append("timing: fewer than three usable bands at the shortest periods, no fit")
    else:
        pr = check["period_range_s"]
        lines.append(f"timing: phase = a - 360 f tau over {check['n_bands']} bands {pr[0]:.4g}-{pr[1]:.4g} s: "
                     f"tau {check['tau_ms']:+.4f} +/- {check['tau_err_ms']:.4f} ms, a "
                     f"{check['intercept_deg']:+.3f} +/- {check['intercept_err_deg']:.3f} deg, "
                     f"chi2/dof {check['chi2_red']:.2f} (tau > 0: the local lags the base)")
        if check["chi2_red"] > TIMING_CHI2_WARN:
            rms, turn = check["residual_rms_deg"], check["turn_deg"]
            if rms < TIMING_TURN_FRACTION * turn:
                lines.append(f"timing: chi2/dof {check['chi2_red']:.1f} over {TIMING_CHI2_WARN:g}, but the residuals "
                             f"({rms:.3f} deg weighted RMS) are under {TIMING_TURN_FRACTION:.0%} of the line's "
                             f"{turn:.1f} deg turn: a delay this large bends each band's phase through the band's "
                             f"averaging over its harmonics and windows, and tau reads as a clock offset")
            else:
                lines.append(f"timing: chi2/dof {check['chi2_red']:.1f} over {TIMING_CHI2_WARN:g} and residuals "
                             f"of {rms:.3f} deg weighted RMS against the line's {turn:.2f} deg turn: the phase is "
                             f"not a line in frequency over these bands, so tau is not a clock offset alone")
    if check.get("determined") is not None:  # None: no fit was made
        for name, el in (check.get("elements") or {}).items():
            if el is not None and el.get("determined") is False:
                lines.append(f"timing: arg {name}: delay not determined: {el['not_determined']}")
            elif el is not None:
                lines.append(f"timing: arg {name}: tau {el['tau_ms']:+.4f} +/- {el['tau_err_ms']:.4f} ms")
    return lines


# --- archives -----------------------------------------------------------------------------------------------


def read_channels(path, station: str, roles, t0_ns: int, n: int, sample_rate: float) -> tuple[dict, dict, dict]:
    """Read a station's channels onto n samples from t0_ns, with their calibration.

    The archive's channels are matched to the roles ex, ey, hx, hy as
    `mt_workbench.crosspower` matches them (a LEMI-424's e1, e2, bx, by
    included). Each run is placed by integer arithmetic from its start; a
    sample no run covers is NaN. Each channel's median over the samples
    read is removed in float64 before the float32 copy, so counts far from
    zero keep their low bits; the estimate does not depend on it.

    Each run is calibrated with its own chain, as aurora calibrates it.
    When the runs read hold one chain, the response is that chain's. When
    a channel's chain changes from one run to the next, its response is a
    `RunResponses` cut at the change, and the first sample of the later
    run is set to NaN when the run before ends next to it: a window across
    the change would hold two chains.

    Args:
        path: The MTH5 archive.
        station (str): The station.
        roles (tuple): Roles to read, e.g. ("ex", "ey").
        t0_ns (int): Time of the first sample, ns since the epoch, on the archive's grid.
        n (int): Samples to read.
        sample_rate (float): The expected rate, Hz.

    Returns:
        tuple: ({role: float32 samples}, {role: callable giving the chain's
        complex response at frequencies, or a `RunResponses`}, {role:
        {"channel", "filters"}} naming the archive channel and the chain's
        filters removed, with "runs", each run's id and filters, when the
        runs read hold more than one chain).

    Raises:
        ValueError: When the station lacks a role, or its rate differs.
    """
    st = _layout(path, station, tuple(roles))
    if abs(st.fs - sample_rate) > 1e-9 * sample_rate:
        raise ValueError(f"{station}: {st.fs:g} Hz in {Path(path).name}, expected {sample_rate:g} Hz")
    arrays, chains, responses = {}, {}, {}
    warned: set = set()
    # the runs that meet the n samples, in grid order: (first sample, run index), placed as _read places them
    placed = []
    for k, run in enumerate(st.runs):
        i0 = int(round((run.start_ns - int(t0_ns)) * st.fs / 1e9))
        if min(int(n), i0 + run.n) > max(0, i0):
            placed.append((max(0, i0), k))
    placed.sort()
    with h5py.File(path, "r") as handle:
        for role in roles:
            raw, covered = _read(st, handle, role, int(t0_ns), int(n), warned)
            out = np.full(int(n), np.nan, dtype=np.float32)
            if covered:
                # the median goes before the float32 cast: counts of 1e7 and more keep their low bits
                step = max(1, sum(b - a for a, b in covered) // 1_000_000)
                median = float(np.median(np.concatenate([raw[a:b:step] for a, b in covered])))
                for a, b in covered:
                    out[a:b] = raw[a:b] - median
            del raw
            run_chains = st.run_chains[role]
            used = [k for _a, k in placed]
            if len({id(run_chains[k]) for k in used}) <= 1:
                k = used[0] if used else 0
                responses[role] = lambda f, role=role, k=k: st.response(role, f, k)
                chains[role] = {"channel": st.names[role], "filters": [f.name for f in run_chains[k][1]]}
            else:
                starts, spans = [], []
                for a, k in placed:
                    if spans and run_chains[k] is run_chains[spans[-1]]:
                        continue
                    if spans and a > 0 and np.isfinite(out[a - 1]):
                        out[a] = np.nan  # a window across the change would hold two chains
                    starts.append(a)
                    spans.append(k)
                starts[0] = 0
                responses[role] = RunResponses(np.asarray(starts, dtype=np.int64),
                                               [lambda f, role=role, k=k: st.response(role, f, k) for k in spans])
                chains[role] = {"channel": st.names[role], "filters": [f.name for f in run_chains[used[0]][1]],
                                "runs": [{"run": st.runs[k].run_id, "filters": [f.name for f in run_chains[k][1]]}
                                         for k in used]}
            arrays[role] = out
    return arrays, responses, chains


def _ns(value) -> int:
    """Return an instant (text, bytes or Timestamp; naive is UTC) as ns since the epoch."""
    t = pd.Timestamp(value.decode() if isinstance(value, bytes) else str(value))
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    return int(t.value)


def archive_runs(path, station: str, roles=()) -> list[tuple[int, int]]:
    """Return the (start, end) ns of a station's runs holding every role, read with h5py.

    Args:
        path: The MTH5 archive.
        station (str): The station.
        roles (tuple): Roles every listed run must hold (`mt_workbench.crosspower._roles`).

    Returns:
        list: (start_ns, end_ns) per run, earliest first; [] for a missing file or station.
    """
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with h5py.File(path, "r") as f:
        for survey_group in f.get("Experiment/Surveys", {}).values():
            group = survey_group.get(f"Stations/{station}")
            if group is None:
                continue
            for run in group.values():
                if not isinstance(run, h5py.Group) or "time_period.start" not in run.attrs:
                    continue
                start, end = _ns(run.attrs["time_period.start"]), _ns(run.attrs["time_period.end"])
                if pd.Timestamp(start).year < 1990 or end <= start:
                    continue
                if roles:
                    try:
                        _roles([k for k in run.keys() if isinstance(run[k], h5py.Dataset)], roles)
                    except ValueError:
                        continue
                out.append((start, end))
    return sorted(out)


# NaN samples between two bursts on the compact grid of `read_bursts`
BURST_GAP = 1


def burst_slots(path, station: str, roles=()) -> dict[int, tuple[str, int]]:
    """Return a burst archive's runs by start, read with h5py.

    A burst site's archive (`mt_workbench.ingest`, `bursts_of:`) holds one run
    per burst.

    Args:
        path: The MTH5 archive.
        station (str): The station.
        roles (tuple): Roles every listed run must hold.

    Returns:
        dict: Start in ns since the epoch to (run id, samples of the
        shortest channel); {} for a missing file or station.
    """
    path = Path(path)
    out: dict[int, tuple[str, int]] = {}
    if not path.exists():
        return out
    with h5py.File(path, "r") as f:
        for survey_group in f.get("Experiment/Surveys", {}).values():
            group = survey_group.get(f"Stations/{station}")
            if group is None:
                continue
            for run_id, run in group.items():
                if not isinstance(run, h5py.Group) or "time_period.start" not in run.attrs:
                    continue
                names = [k for k in run.keys() if isinstance(run[k], h5py.Dataset)]
                if not names:
                    continue
                if roles:
                    try:
                        _roles(names, roles)
                    except ValueError:
                        continue
                out[_ns(run.attrs["time_period.start"])] = (run_id, min(int(run[k].shape[0]) for k in names))
    return dict(sorted(out.items()))


def _chain_names(dataset) -> tuple:
    """Return the filter names a channel dataset's metadata lists, in order."""
    import json

    raw = dataset.attrs.get("filters")
    if raw is None:
        return ()
    entries = json.loads(raw.decode() if isinstance(raw, bytes) else str(raw))
    return tuple(e["applied_filter"]["name"] for e in entries)


def read_bursts(path, station: str, roles, slots_ns, n: int, sample_rate: float) -> tuple[dict, dict, dict]:
    """Read a burst site's channels on a compact grid: the bursts back to back.

    The bursts starting at `slots_ns` are laid one after another, the first
    `n` samples of each, with `BURST_GAP` NaN samples between two bursts,
    so that `band_spectra` treats the joins as gaps and no window straddles
    two bursts, and the memory is that of the bursts alone (the dense grid
    of `read_channels` holds the 28 s between two 2 s bursts as well). The
    grid's sample i is not at a fixed time: the jackknife's time slices
    fall on equal counts of bursts, in time order. The calibration is the
    first slot's run's chain, as `read_channels` takes it, and every other
    run's channels must name the same filters.

    Args:
        path: The MTH5 archive of a burst site.
        station (str): The station.
        roles (tuple): Roles to read.
        slots_ns (list of int): Burst starts, ns since the epoch, in time
            order (`burst_slots`; for a pair, the starts the sites share).
        n (int): Samples taken from each burst.
        sample_rate (float): The expected rate, Hz.

    Returns:
        tuple: As `read_channels`: ({role: float32 samples}, {role:
        callable giving the chain's complex response at frequencies},
        {role: {"channel", "filters"}}).

    Raises:
        ValueError: When a slot has no run, a run holds fewer than `n`
            samples, its rate differs, or a run's channel names other
            filters than the first run's.
    """
    runs = burst_slots(path, station, roles)
    slots_ns = [int(s) for s in slots_ns]
    missing = [s for s in slots_ns if s not in runs]
    if missing:
        raise ValueError(f"{station}: {len(missing)} burst slot(s) not in {Path(path).name}, the first at "
                         f"{pd.Timestamp(missing[0], unit='ns', tz='UTC').isoformat()}")
    short = [runs[s][0] for s in slots_ns if runs[s][1] < n]
    if short:
        raise ValueError(f"{station}: run {short[0]} holds fewer than {n} samples")
    first_run = runs[slots_ns[0]][0]
    m = MTH5()
    m.open_mth5(Path(path), mode="r")
    try:
        survey = m.surveys_group.groups_list[0]
        group = m.get_station(station, survey=survey).get_run(first_run)
        names = _roles(group.groups_list, tuple(roles))
        chains, fs = {}, None
        for role, name in names.items():
            ch = m.get_channel(station, first_run, name, survey)
            fs = float(ch.metadata.sample_rate)
            response = ch.channel_response
            idx = response.get_indices_of_filters_to_remove(include_decimation=False, include_delay=False)
            idx = [i for i in idx if ch.metadata.filters[i].applied]
            chains[role] = (response, [response.filters_list[i] for i in idx])
    finally:
        m.close_mth5()
    if abs(fs - sample_rate) > 1e-9 * sample_rate:
        raise ValueError(f"{station}: {fs:g} Hz in {Path(path).name}, expected {sample_rate:g} Hz")
    step = n + BURST_GAP
    total = len(slots_ns) * step - BURST_GAP
    arrays, labels = {}, {}
    with h5py.File(path, "r") as f:
        base = next(g[f"Stations/{station}"] for g in f["Experiment/Surveys"].values()
                    if f"Stations/{station}" in g)
        for role, name in names.items():
            want = _chain_names(base[first_run][name])
            out = np.full(total, np.nan, dtype=np.float64)
            for k, slot in enumerate(slots_ns):
                dataset = base[runs[slot][0]][name]
                if _chain_names(dataset) != want:
                    raise ValueError(f"{station} {runs[slot][0]} {name}: filters {_chain_names(dataset)}, the first "
                                     f"run {first_run} has {want}: one chain is taken for every burst")
                out[k * step:k * step + n] = dataset[:n]
            out -= np.nanmedian(out[::max(1, total // 1_000_000)])
            arrays[role] = out.astype(np.float32)
            labels[role] = {"channel": name, "filters": [f.name for f in chains[role][1]]}

    def respond(role, freqs):
        response, filters = chains[role]
        if not filters:
            return np.ones(np.asarray(freqs).size, dtype=complex)
        return np.asarray(response.complex_response(freqs, filters_list=filters), dtype=complex)

    responses = {role: (lambda f, role=role: respond(role, f)) for role in names}
    return arrays, responses, labels


def overlap_hours(runs, lo_ns: int, hi_ns: int) -> float:
    """Return the hours of [lo_ns, hi_ns) the runs cover."""
    return sum(max(0, min(e, hi_ns) - max(s, lo_ns)) for s, e in runs) / 3.6e12


def select_stack(survey: Survey, local: str | None, base: str | None, lo_ns: int, hi_ns: int, roles, exclude=(),
                 min_overlap_hours: float = MIN_OVERLAP_HOURS, rate: float | None = None,
                 runs_of=None, edge_s: float | None = None) -> tuple[list[dict], list[dict]]:
    """Choose the stack's members among the survey's sites.

    A member is a site of survey.yaml at the local's sample rate (or at
    `rate`) whose raw archive holds runs with both `roles` covering
    [lo_ns, hi_ns) by at least `min_overlap_hours`, or by the whole window
    when it is shorter, less one sample period: a run ends at its last
    sample (`archive_runs`), so a record that holds every sample of the
    window covers it one sample short (workbench issue 27). With `edge_s`
    given and the window the shorter, a site is also a member when its
    runs, merged across gaps of at most `edge_s`, hold one span that starts
    no later than `edge_s` after the window's start and ends no earlier
    than `edge_s` before its end. With `edge_s` = `MEMBER_EDGE_S` this is
    the record `member_changes` reads as no change, the rule for a base
    stack (upstream 89). The local, the base and the sites in
    `exclude` are never members. Archives are opened read-only and no
    variant is built.

    Args:
        survey (Survey): The survey.
        local (str or None): Local site; None only with `rate`, for a stack
            judged without a pair.
        base (str or None): Base site; None when the stack is the base.
        lo_ns, hi_ns (int): The window, ns since the epoch.
        roles (tuple): The channels the stack takes, ("ex", "ey") or ("hx", "hy").
        exclude (iterable of str): Sites left out by request.
        min_overlap_hours (float): Overlap a member needs.
        rate (float, optional): The members' sample rate, Hz. None takes
            the local's.
        runs_of (callable, optional): ``runs_of(site, path, roles)`` giving
            a site's runs as `archive_runs` would, or None when they are not
            read yet (the site is then left out as `NOT_READ`). It is called
            in place of `archive_runs` once the raw archive's path exists,
            so no archive is opened. None reads each archive.
        edge_s (float, optional): Seconds a member may start late or end
            early when the window is shorter than `min_overlap_hours`.
            None asks for the whole window less one sample period.

    Returns:
        tuple: (members, left_out): each a list of dicts, ``site`` and
        ``overlap_h`` for a member, ``site`` and ``reason`` for a site left out.

    Raises:
        ValueError: With neither a local nor a rate, or a local at another
            rate than `rate`.
    """
    exclude = set(exclude or ())
    window_h = (hi_ns - lo_ns) / 3.6e12
    need = min(float(min_overlap_hours), window_h)
    edge = None if edge_s is None else int(round(float(edge_s) * 1e9))
    # the edges allowed: with edge_s, when the whole window is asked for and it is longer than both edges
    edges = (lo_ns + edge, hi_ns - edge) if edge is not None and need >= window_h and hi_ns - lo_ns > 2 * edge else None
    if rate is None:
        if local is None:
            raise ValueError("select_stack: give the local or the stack's rate")
        rate = survey.sample_rate_of(local)
    else:
        rate = float(rate)
        if local is not None and not math.isclose(survey.sample_rate_of(local), rate, rel_tol=1e-9):
            raise ValueError(f"the local {local} is at {survey.sample_rate_of(local):g} Hz, the stack at {rate:g} Hz")
    at = "the pair" if local is not None else "the stack"
    roles = tuple(roles)
    members, left_out = [], []
    for site in survey.site_names():
        reason = None
        if site == local:
            reason = "the local"
        elif site == base:
            reason = "the base"
        elif site in exclude:
            reason = "excluded on request"
        elif not math.isclose(survey.sample_rate_of(site), rate, rel_tol=1e-9):
            reason = f"{survey.sample_rate_of(site):g} Hz, {at} is at {rate:g} Hz"
        else:
            path = default_archive_path(survey, site)
            runs = None
            if not path.exists():
                reason = f"no archive at {path}"
            else:
                runs = archive_runs(path, site, roles) if runs_of is None else runs_of(site, path, roles)
                if runs is None:
                    reason = NOT_READ
            if runs is not None:
                hours = overlap_hours(runs, lo_ns, hi_ns)
                # one sample period of slack: the run's end is its last sample, not the instant after it
                within = edges is not None and any(a <= edges[0] and b >= edges[1] for a, b in _merge_runs(runs, edge))
                if hours < need - 1.0 / (rate * 3600.0) - 1e-9 and not within:
                    reason = (f"its runs with {'/'.join(roles)} cover {hours:.2f} h of the window, under "
                              f"{need:g} h" + (f" less {edge_s:g} s at an edge" if edges else ""))
                else:
                    members.append({"site": site, "overlap_h": round(hours, 4)})
        if reason:
            left_out.append({"site": site, "reason": reason})
    unknown = sorted(exclude - set(survey.site_names()))
    if unknown:
        logger.warning(f"exclude names sites survey.yaml does not hold: {unknown}")
    return members, left_out


def stack_channels(survey: Survey, members, roles, t0_ns: int, n: int, sample_rate: float,
                   use_filters: bool = True) -> tuple[dict, list[dict]]:
    """Build the plain stack of the members' channels on n samples from t0_ns, in the time domain.

    Each member's channel is read from its processing archive
    (`mt_workbench.ingest.processing_archive`, which builds a stale or
    missing filtered variant), loses its median, is divided by its RMS over
    the samples it covers, and is added to the plain mean of the members
    present at each sample (see The stack in the module docstring). A
    sample no member covers is NaN.

    Args:
        survey (Survey): The survey.
        members (list): Member site names, or the dicts `select_stack` returns.
        roles (tuple): The channels, ("ex", "ey") or ("hx", "hy").
        t0_ns (int): First sample, ns since the epoch.
        n (int): Samples.
        sample_rate (float): Rate, Hz.
        use_filters (bool): Read the filtered variants (False: the raw archives).

    Returns:
        tuple: ({role: float32 stack}, [per member: site, archive, channels,
        coverage (fraction of the n samples), rms per role in counts]).

    Raises:
        ValueError: When no member is given, or none has a live channel.
    """
    names = [m["site"] if isinstance(m, dict) else str(m) for m in members]
    if not names:
        raise ValueError("the stack has no member")
    sums = {r: np.zeros(int(n), dtype=np.float32) for r in roles}
    counts = {r: np.zeros(int(n), dtype=np.uint16) for r in roles}
    info = []
    for site in names:
        path = processing_archive(survey, site, use_filters)
        warn_without_h_polarity(path, site)
        arrays, _responses, chains = read_channels(path, site, roles, t0_ns, n, sample_rate)
        entry = {"site": site, "archive": str(path), "channels": {r: chains[r]["channel"] for r in roles},
                 "rms": {}, "coverage": None}
        for role in roles:
            x = arrays.pop(role)
            ok = np.isfinite(x)
            entry["coverage"] = round(float(ok.mean()), 6)
            if not ok.any():
                entry["rms"][role] = None
                continue
            step = max(1, x.size // 2_000_000)
            sub = x[::step]
            sub = sub[np.isfinite(sub)].astype(np.float64)
            med = float(np.median(sub))
            rms = float(np.sqrt(np.mean((sub - med) ** 2)))
            entry["rms"][role] = rms
            if not rms > 0:
                logger.warning(f"stack member {site} {role}: flat over the window, left out of that channel")
                continue
            x -= np.float32(med)
            x /= np.float32(rms)
            sums[role][ok] += x[ok]
            counts[role][ok] += 1
            del x, ok
        info.append(entry)
        logger.info(f"stack member {site}: coverage {entry['coverage']:.3f}, rms "
                    + ", ".join(f"{r} {entry['rms'][r]:.4g}" if entry["rms"].get(r) else f"{r} -" for r in roles))
    out = {}
    for role in roles:
        c = counts.pop(role)
        if not c.any():
            raise ValueError(f"no stack member has a live {role}")
        s = sums.pop(role)
        live = c > 0
        s[live] /= c[live]
        s[~live] = np.nan
        out[role] = s
    return out, info


def stack_band(spectra: np.ndarray, reject_factor: float = STACK_REJECT_FACTOR,
               min_members: int = STACK_MIN_MEMBERS, method: str = "mean") -> dict:
    """Stack one channel of the members in one band, leaving out each member's windows far above the array level.

    A member is present in a window when its spectra there are finite.
    Its scale is the square root of the median over its present windows of
    its band power (the mean of |x|^2 over the harmonics); its normalised
    power is the band power over the scale squared. The array level of a
    window is the median of the normalised power over the members present;
    a member is rejected in a window where its normalised power exceeds
    `reject_factor` times the level. The stack is the mean (or, with
    ``method="median"``, the marginal median) of the kept members' spectra
    divided by their scales (see The stack in the module docstring).

    Args:
        spectra (np.ndarray): Complex [members, windows, harmonics], NaN
            where a member is absent.
        reject_factor (float): The rejection threshold, over 1.
        min_members (int): Kept members a window needs, at least 1.
        method (str): One of `STACK_METHODS`: ``"mean"`` or ``"median"``.

    Returns:
        dict: ``stack`` complex64 [windows, harmonics] (NaN where fewer
        than `min_members` are kept), ``count`` (kept members per window),
        ``scale`` [members] (NaN for a member absent or flat in the band),
        ``power`` [members, windows] (normalised, NaN where absent),
        ``level`` [windows], ``present`` and ``rejected`` [members, windows].

    Raises:
        ValueError: For a threshold of 1 or less, `min_members` under 1,
            or a method not in `STACK_METHODS`.
    """
    if not reject_factor > 1.0:
        raise ValueError(f"reject_factor {reject_factor}: must exceed 1, or members at the array level are rejected")
    if int(min_members) < 1:
        raise ValueError(f"min_members {min_members}: at least 1")
    if method not in STACK_METHODS:
        raise ValueError(f"stack method {method!r}: one of {STACK_METHODS}")
    X = np.asarray(spectra)
    n_members, n_windows, n_harm = X.shape
    present = np.all(np.isfinite(X), axis=2)
    band_power = np.mean(np.abs(X) ** 2, axis=2, dtype=np.float64)
    scale = np.full(n_members, np.nan)
    power = np.full((n_members, n_windows), np.nan)
    for m in range(n_members):
        live = present[m]
        if not live.any():
            continue
        s2 = float(np.median(band_power[m, live]))
        if s2 > 0 and np.isfinite(s2):
            scale[m] = math.sqrt(s2)
            power[m, live] = band_power[m, live] / s2
    usable = np.isfinite(power)
    level = np.full(n_windows, np.nan)
    some = usable.any(axis=0)
    level[some] = np.nanmedian(power[:, some], axis=0)
    with np.errstate(invalid="ignore"):
        rejected = usable & (power > reject_factor * level[None, :])
    kept = usable & ~rejected
    count = kept.sum(axis=0)
    stack = np.full((n_windows, n_harm), np.nan + 1j * np.nan, dtype=np.complex64)
    ok = count >= int(min_members)
    if method == "median":
        stack[ok] = _kept_median(X, scale, kept, ok, count)
    else:
        acc = np.zeros((n_windows, n_harm), dtype=np.complex128)
        for m in range(n_members):
            if kept[m].any():
                acc[kept[m]] += X[m, kept[m]] / scale[m]
        stack[ok] = (acc[ok] / count[ok, None]).astype(np.complex64)
    return {"stack": stack, "count": count, "scale": scale, "power": power, "level": level, "present": usable,
            "rejected": rejected}


def _kept_median(X: np.ndarray, scale: np.ndarray, kept: np.ndarray, ok: np.ndarray,
                 count: np.ndarray) -> np.ndarray:
    """Return the marginal median of the kept members' scaled spectra on the windows `ok`, complex64.

    The real and imaginary parts are filled into float64 [members, ok
    windows, harmonics] arrays, NaN where a member is not kept, sorted
    along the members (NaN sorts last), and each window's median is the
    mean of its values at ranks (k - 1) // 2 and k // 2 of its k kept
    members: numpy's nanmedian values without reducing a slice that is all
    NaN, and in about a third of its time. Each member's values are divided by
    its scale as the mean's are, so two kept members give the mean bit for
    bit.

    Args:
        X (np.ndarray): Complex [members, windows, harmonics].
        scale (np.ndarray): Each member's scale [members].
        kept (np.ndarray): Bool [members, windows], the members kept.
        ok (np.ndarray): Bool [windows], the windows to fill (count >= min_members, at least 1).
        count (np.ndarray): Kept members per window [windows].

    Returns:
        np.ndarray: complex64 [ok windows, harmonics].
    """
    idx = np.flatnonzero(ok)
    n_members, n_harm = X.shape[0], X.shape[2]
    shape = (n_members, idx.size, n_harm)
    parts = {"real": np.full(shape, np.nan), "imag": np.full(shape, np.nan)}
    for m in range(n_members):
        rows = kept[m, idx]
        if rows.any():
            y = X[m, idx[rows]] / scale[m]  # the mean's own division, so the values are identical
            parts["real"][m, rows] = y.real
            parts["imag"][m, rows] = y.imag
            del y
    k = count[idx]
    lo, hi = ((k - 1) // 2)[None, :, None], (k // 2)[None, :, None]
    out = np.empty((idx.size, n_harm), dtype=np.complex64)
    for name, values in parts.items():
        values.sort(axis=0)
        # each part is set on its own: re + 1j * im would turn a real part of -0.0 into +0.0
        setattr(out, name, (np.take_along_axis(values, lo, 0)[0] + np.take_along_axis(values, hi, 0)[0]) / 2)
    return out


def band_stack(bands, members, out_keys: dict, reject_factor: float = STACK_REJECT_FACTOR,
               min_members: int = STACK_MIN_MEMBERS, record: list | None = None, method: str = "mean"):
    """Yield each band with the members' channels replaced by their band-domain stack.

    Each channel of the stack is `stack_band` of the members' same channel.
    A window where either channel keeps fewer than `min_members` is left
    out of the band; a band left with fewer than `MIN_LEVEL_WINDOWS`
    windows is not yielded. The members' channels leave the band, so the
    estimator sees the pair's channels and the stack's only.

    Args:
        bands: BandSpectra, from `band_spectra` with the members' channels
            given as optional.
        members (list): (name, {role: channel key}) per member.
        out_keys (dict): Role to the stack's channel key, e.g.
            {"ex": "r_ex", "ey": "r_ey"}; each member maps every role.
        reject_factor (float): `stack_band`'s threshold.
        min_members (int): Kept members a window needs, at most the members given.
        record (list, optional): One dict appended per band: period, level,
            f_lo, f_hi, windows (the band's), left_out (windows with too few
            members kept), estimated (False for a band not yielded),
            members, {name: {role: {scale, present (fraction of the band's
            windows), rejected (fraction of the windows present)}}}, and
            stack_scale_rms, {role: the root mean square of the members'
            finite scales, None without one} (Units on the stack in the
            module docstring).
        method (str): `stack_band`'s method, one of `STACK_METHODS`.

    Yields:
        BandSpectra: The band with the stack's channels and its kept windows.

    Raises:
        ValueError: With no member, `min_members` over the members, a
            member lacking a role, or a method not in `STACK_METHODS`.
    """
    if method not in STACK_METHODS:
        raise ValueError(f"stack method {method!r}: one of {STACK_METHODS}")
    members = [(str(name), dict(keys)) for name, keys in members]
    if not members:
        raise ValueError("the stack has no member")
    if int(min_members) > len(members):
        raise ValueError(f"min_members {min_members}: the stack has {len(members)} member(s)")
    for name, keys in members:
        missing = sorted(set(out_keys) - set(keys))
        if missing:
            raise ValueError(f"stack member {name} lacks {missing}")
    for band in bands:
        spectra = dict(band.spectra)
        nw = band.n_windows
        keep = np.ones(nw, dtype=bool)
        stacks = {}
        entry = {"period": float(band.period), "level": int(band.level), "f_lo": float(band.f_lo),
                 "f_hi": float(band.f_hi), "windows": int(nw), "left_out": 0, "estimated": True,
                 "members": {name: {} for name, _keys in members}, "stack_scale_rms": {}}
        for role, out_key in out_keys.items():
            res = stack_band(np.stack([spectra.pop(keys[role]) for _name, keys in members]), reject_factor,
                             min_members, method)
            keep &= res["count"] >= int(min_members)
            stacks[out_key] = res["stack"]
            finite = res["scale"][np.isfinite(res["scale"])]
            entry["stack_scale_rms"][role] = float(np.sqrt(np.mean(finite**2))) if finite.size else None
            for m, (name, _keys) in enumerate(members):
                n_present = int(res["present"][m].sum())
                entry["members"][name][role] = {
                    "scale": float(res["scale"][m]) if np.isfinite(res["scale"][m]) else None,
                    "present": round(n_present / nw, 6) if nw else 0.0,
                    "rejected": round(int(res["rejected"][m].sum()) / n_present, 6) if n_present else None}
            del res
        entry["left_out"] = int(nw - keep.sum())
        if keep.sum() < MIN_LEVEL_WINDOWS:
            entry["estimated"] = False
            logger.warning(f"band stack, L{band.level} {band.period:.4g} s: {int(keep.sum())} of {nw} windows keep "
                           f"{min_members} member(s), the band is left out")
        if record is not None:
            record.append(entry)
        if not entry["estimated"]:
            continue
        spectra.update(stacks)
        yield BandSpectra(band.level, band.f_lo, band.f_hi, band.freqs, band.t_mid[keep], band.record_s,
                          {key: value[keep] for key, value in spectra.items()})


def _merge_runs(runs, gap_ns: int) -> list[tuple[int, int]]:
    """Return (start, end) spans with the runs merged across gaps of at most gap_ns."""
    out: list[list[int]] = []
    for start, end in sorted(runs):
        if out and start - out[-1][1] <= gap_ns:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def member_changes(survey: Survey, members, roles, lo_ns: int, hi_ns: int,
                   edge_s: float = MEMBER_EDGE_S, runs_of=None) -> list[dict]:
    """List where a stack member's record starts or ends inside a window, from the archives' metadata.

    Each member's runs holding `roles` in its raw archive
    (`archive_runs`, or `runs_of`) are merged across gaps of at most
    `edge_s`; a merged span's start or end more than `edge_s` inside
    [lo_ns, hi_ns) is a change of the stack's membership (see The stack as
    the base in the module docstring). No sample is read.

    Args:
        survey (Survey): The survey.
        members (list): Member site names, or the dicts `select_stack` returns.
        roles (tuple): The stack's channels.
        lo_ns, hi_ns (int): The window, ns since the epoch.
        edge_s (float): The tolerance at the edges and across gaps, s.
        runs_of (callable, optional): ``runs_of(site, path, roles)`` giving
            a member's runs as `archive_runs` would, or None when they are
            not read yet (no change is then named for that member). It is
            called in place of `archive_runs`, so no archive is opened.
            None reads each archive.

    Returns:
        list: One dict per change, earliest first: ``site``, ``change``
        ("starts" or "ends") and ``time_ns``.
    """
    edge = int(round(float(edge_s) * 1e9))
    out = []
    for m in members:
        site = m["site"] if isinstance(m, dict) else str(m)
        path = default_archive_path(survey, site)
        runs = archive_runs(path, site, roles) if runs_of is None else runs_of(site, path, roles)
        if runs is None:
            continue
        spans = _merge_runs(runs, edge)
        for start, end in spans:
            for t, what in ((start, "starts"), (end, "ends")):
                if lo_ns + edge < t < hi_ns - edge:
                    out.append({"site": site, "change": what, "time_ns": int(t)})
    return sorted(out, key=lambda c: (c["time_ns"], c["site"]))


def polarity_band(spectra: np.ndarray, reject_factor: float = STACK_REJECT_FACTOR) -> np.ndarray:
    """Return each member's correlation with the mean of the other members in one band of one channel.

    Each member is divided by its per-band scale and loses the windows
    `stack_band` rejects (with `reject_factor`). For member m, s is the
    mean of the other members kept in a window, and the correlation is
    Re(sum x conj(s)) / sqrt(sum |x|^2 sum |s|^2) over the windows where m
    is kept and another member is, and over the band's harmonics.

    Args:
        spectra (np.ndarray): Complex [members, windows, harmonics], NaN where a member is absent.
        reject_factor (float): `stack_band`'s threshold.

    Returns:
        np.ndarray: [members] correlations in [-1, 1]; NaN for a member
        with no window shared with another.
    """
    X = np.asarray(spectra)
    res = stack_band(X, reject_factor, 1)
    kept = res["present"] & ~res["rejected"]
    n_members, n_windows, n_harm = X.shape
    total = np.zeros((n_windows, n_harm), dtype=np.complex128)
    for m in range(n_members):
        if kept[m].any():
            total[kept[m]] += X[m, kept[m]] / res["scale"][m]
    count = kept.sum(axis=0)
    out = np.full(n_members, np.nan)
    for m in range(n_members):
        use = kept[m] & (count - 1 >= 1)
        if not use.any():
            continue
        x = X[m, use].astype(np.complex128) / res["scale"][m]
        others = (total[use] - x) / (count[use] - 1)[:, None]
        den = math.sqrt(float(np.sum(np.abs(x) ** 2)) * float(np.sum(np.abs(others) ** 2)))
        if den > 0:
            out[m] = float(np.real(np.sum(x * np.conj(others)))) / den
    return out


def polarity_screen(bands, members, roles, periods=POLARITY_PERIODS, reject_factor: float = STACK_REJECT_FACTOR,
                    record: list | None = None):
    """Yield the bands unchanged, recording each member channel's correlation with the other members.

    For each band whose period lies in `periods` (inclusive) and each role,
    `polarity_band` of the members' channel is recorded.

    Args:
        bands: BandSpectra holding the members' channels (`band_spectra` with them as optional).
        members (list): (name, {role: channel key}) per member.
        roles (tuple): The channels screened, e.g. ("ex", "ey").
        periods (tuple): The shortest and longest period screened, s.
        reject_factor (float): `stack_band`'s threshold.
        record (list, optional): One dict appended per band screened:
            period, level and members, {name: {role: correlation or None}}.

    Yields:
        BandSpectra: Each band as it came.
    """
    members = [(str(name), dict(keys)) for name, keys in members]
    lo, hi = float(periods[0]), float(periods[1])
    for band in bands:
        if record is not None and members and lo * (1 - 1e-9) <= band.period <= hi * (1 + 1e-9):
            entry = {"period": float(band.period), "level": int(band.level),
                     "members": {name: {} for name, _keys in members}}
            for role in roles:
                corr = polarity_band(np.stack([band.spectra[keys[role]] for _name, keys in members]), reject_factor)
                for (name, _keys), c in zip(members, corr):
                    entry["members"][name][role] = round(float(c), 6) if np.isfinite(c) else None
            record.append(entry)
        yield band


def polarity_summary(record: list, members, roles) -> list[dict]:
    """Return each member channel's median correlation over the screened bands, and whether it is flagged.

    Args:
        record (list): `polarity_screen`'s record.
        members (list): Member names, in the stack's order.
        roles (tuple): The channels screened.

    Returns:
        list: One dict per member and role: ``site``, ``channel``,
        ``correlation`` (the median over the bands with a value, None
        without one), ``bands`` (how many) and ``flagged`` (a negative
        median).
    """
    out = []
    for name in members:
        for role in roles:
            values = [b["members"][name][role] for b in record
                      if name in b["members"] and b["members"][name].get(role) is not None]
            med = float(np.median(values)) if values else None
            out.append({"site": name, "channel": role, "correlation": None if med is None else round(med, 6),
                        "bands": len(values), "flagged": bool(med is not None and med < 0)})
    return out


# --- products -----------------------------------------------------------------------------------------------


def write_csv(est: TensorEstimate, letter: str, path) -> Path:
    """Write the estimate as CSV, one row per band (`TensorEstimate.frame`); floats round-trip exactly."""
    path = Path(path)
    est.frame(letter).to_csv(path, index=False, float_format="%.17g")
    return path


def read_csv(path) -> tuple[TensorEstimate, str]:
    """Read a CSV `write_csv` wrote; return (TensorEstimate, letter).

    pandas' default float parser may round the last digit; the round-trip
    parser gives back the values written.
    """
    return TensorEstimate.from_frame(pd.read_csv(path, float_precision="round_trip"))


def write_h5(est: TensorEstimate, letter: str, path, attrs: dict | None = None) -> Path:
    """Write the estimate's arrays to a plain HDF5 file (h5py), one dataset per array.

    mt_metadata's transfer-function object takes hx, hy as inputs and
    labels a 2 x 2 output on ex, ey as an impedance in mV/km/nT, so a T or
    M stored there would read back as Z; the arrays are stored as they are
    instead, with the tensor's letter, units and conventions as attributes.

    Args:
        est (TensorEstimate): The estimate.
        letter (str): "T" or "M".
        path: The file to write.
        attrs (dict, optional): More root attributes (str, number or list of str).

    Returns:
        Path: The file.
    """
    path = Path(path)
    with h5py.File(path, "w") as f:
        f.attrs["tensor"] = letter
        f.attrs["units"] = UNITS
        f.attrs["layout"] = ("tensor[band, i, j]: output i (x, y) on input j (x, y); "
                             "numpy forward FFT, phase -360 f tau for a local lagging the base by tau")
        for key, value in (attrs or {}).items():
            f.attrs[key] = value if not isinstance(value, (list, tuple)) else [str(v) for v in value]
        for name in ("period", "f_lo", "f_hi", "f_mean", "f_weighted", "level", "n_windows", "n_harm", "n_groups",
                     "tensor",
                     "sigma", "det", "abs_det_err", "half_arg_deg", "half_arg_err_deg", "coh_out", "coh_in",
                     "coh_out_weighted", "frac_downweighted"):
            f.create_dataset(name, data=getattr(est, name))
        for name, values in est.flags().items():  # derived from the arrays above, stored for other readers
            f.create_dataset(name, data=values)
        f.attrs["flag_limits"] = (f"flag_few_groups: n_groups under {FLAG_MIN_GROUPS} on an estimated row; "
                                  f"flag_low_coherence: coh_out_weighted of either row under {FLAG_COHERENCE:g}")
        f.attrs["coherence"] = ("coh_out, coh_in: squared multiple coherence on the reference, every sample "
                                "weighted 1; coh_out_weighted: that of each output under its row's final Huber "
                                "weights; frac_downweighted: each row's fraction of samples with a weight under 1")
    return path


def read_h5(path) -> tuple[TensorEstimate, str, dict]:
    """Read a file `write_h5` wrote; return (TensorEstimate, letter, root attributes)."""
    with h5py.File(path, "r") as f:
        attrs = {k: (v.decode() if isinstance(v, bytes) else v) for k, v in f.attrs.items()}
        data = {name: f[name][()] for name in f}
    data.setdefault("f_weighted", data["f_mean"])  # a file written before f_weighted was added
    # a file written before the weighted coherence was added lacks it, and the estimate fills it with NaN
    est = TensorEstimate(**{k: data[k] for k in TensorEstimate.__dataclass_fields__ if k in data})
    return est, str(attrs["tensor"]), attrs


def plot_estimate(est: TensorEstimate, letter: str, path, title: str = "", timing: dict | None = None) -> Path:
    """Draw the estimate: magnitude and phase per element, and arg(det) / 2 with error bars.

    For M the magnitude panel shows |M - I| per element; for T, |T|. The
    third panel draws the timing check's line over the bands it fitted.

    Args:
        est (TensorEstimate): The estimate.
        letter (str): "T" or "M".
        path: The PNG to write.
        title (str): Figure title.
        timing (dict, optional): `timing_check` of the estimate.

    Returns:
        Path: The PNG.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = Path(path)
    fig, axes = plt.subplots(3, 1, figsize=(8.5, 11), sharex=True)
    shown = est.tensor - (np.eye(2)[None] if letter == "M" else 0.0)
    for k, el in enumerate(ELEMENTS):
        i, j = divmod(k, 2)
        z, s = shown[:, i, j], est.sigma[:, i, j]
        axes[0].errorbar(est.period, np.abs(z), yerr=s, fmt="o-", ms=3, lw=0.8, capsize=2, label=f"{letter}{el}")
        zt = est.tensor[:, i, j]
        axes[1].errorbar(est.period, np.degrees(np.angle(zt)), yerr=np.degrees(s / np.abs(zt)), fmt="o-", ms=3,
                         lw=0.8, capsize=2, label=f"{letter}{el}")
    axes[0].set_yscale("log")
    axes[0].set_ylabel(f"|{letter} - I|" if letter == "M" else f"|{letter}|")
    axes[1].set_ylabel(f"arg {letter} (deg)")
    axes[1].set_ylim(-180, 180)
    axes[2].errorbar(est.period, est.half_arg_deg, yerr=est.half_arg_err_deg, fmt="ko", ms=3, capsize=2,
                     label=f"arg(det {letter}) / 2")
    if timing and timing.get("tau_ms") is not None and np.isfinite(timing["tau_ms"]):
        pr = timing["period_range_s"]
        sel = (est.period >= pr[0] * (1 - 1e-9)) & (est.period <= pr[1] * (1 + 1e-9))
        f = est.f_weighted[sel]
        line = timing["intercept_deg"] - 360.0 * f * timing["tau_ms"] * 1e-3
        line = (line + 90.0) % 180.0 - 90.0  # onto the data's branch, arg(det) / 2 in [-90, 90)
        order = np.argsort(est.period[sel])
        x, line = est.period[sel][order], line[order]
        jumps = np.flatnonzero(np.abs(np.diff(line)) > 90.0) + 1
        x, line = np.insert(x, jumps, np.nan), np.insert(line, jumps, np.nan)
        axes[2].plot(x, line, "r-", lw=1.2,
                     label=f"fit: tau {timing['tau_ms']:+.3f} +/- {timing['tau_err_ms']:.3f} ms")
    axes[2].axhline(0.0, color="0.6", lw=0.6)
    axes[2].set_ylabel(f"arg(det {letter}) / 2 (deg)")
    axes[2].set_xlabel("period (s)")
    axes[2].set_xscale("log")
    for ax in axes:
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8, ncol=4)
    if title:
        fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path
