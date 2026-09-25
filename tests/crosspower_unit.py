# -*- coding: utf-8 -*-
"""
Unit test for crust.crosspower

Tests compute_windows, bin_windows, band_view, masked_chunks,
stack_impedance and chunk_impedances on synthetic MTH5 archives. A local
station L (ex ey hx hy) and a remote R (hx hy) at 100 Hz, int32 counts, are
written as real MTH5 archives the way `tests/virtual_unit.py` writes its
members (RunTS / `from_runts`, no filters, so every response is 1). One
white "field" pair Hx, Hy runs from T0 - 100 s to T0 + 3200 s; L records it
in two runs, [T0, T0 + 1500 s) and [T0 + 1600 s, T0 + 3100 s) (a 100 s gap),
R in one run over the whole span. L's coils add their own noise (0.3 of the
field rms: a single-station estimate would come out ~8 % low), R's coils
theirs (0.3), and L's electrics are

    Ex = 0.3 Hx + 2.0 Hy(t - 1 sample) + noise,   Ey = -1.5 Hx - 0.2 Hy + noise

(noise 0.1 of their rms), so the band's Zxy is 2 <exp(-2 pi i f / 100)> over
its harmonics, Zyx -1.5.

Chunk 3 ([1800, 2400) s) adds a burst to Ex alone: white noise 10 times its
rms, which Hx, Hy do not predict. T0 is a multiple of 600 s from the epoch,
so the 600 s base grid starts at T0. At 100 Hz the binned levels are 0-2
(1.28, 5.12, 20.48 s windows), the stream levels 3-8 (81.9 s to 23 h), and
with 600 s chunks the display multiples are 1, 1, 1, 2, 5, 18, 70, 280, 560.
The store covers [T0, T0 + 3000 s) (five 600 s chunks) unless said
otherwise.

Usage:
    python tests/crosspower_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. the windows the store keeps at any level are not, start for start, the
   windows of the continuous grid (window w of level L at base sample
   w * 64 * 4**L from the epoch) whose span lies in [T0, T0 + 3000 s) and
   touches no gap, computed here on the global sample index: L's uncovered
   samples (before T0, [1500, 1600) s and from 3100 s) dilated level by
   level as `decimation_levels` dilates them (a // 4 - 32, b // 4 + 1 + 32),
   plus, from level 3 on, the stitched stream's ends (T0 - 64 s and
   T0 + 3064 s, the first block's read start and the last one's read end)
   as gaps at level 2; or the grid count it reports (n_possible) differs
   from the grid counted here: kept / grid 4528 / 4686, 1127 / 1170,
   277 / 291, 66 / 71, 12 / 16, 0 / 3 at levels 0-5 (0 / 0 at 6-8). A
   window lost or counted twice at a block edge fails this. Here the
   stream's ends lie inside L's own gaps and drop no window by themselves
   (the counts are the same without them); criterion 16 is the one a
   stream whose ends are not gaps fails;
2. the stitched level-2 stream (6.25 Hz) differs, over
   [T0 + 200, T0 + 1300) s, from the level-2 decimation computed here with
   scipy.signal.decimate (x4 twice, FIR, zero phase, float64) of L's first
   run as generated, by more than 1e-4 of that signal's rms on any channel
   (both with their median over the span removed). A stream without the
   block medians added back steps at every block edge (by the difference of
   two blocks' medians, a few counts on a 1000-count signal) and fails
   this, as does a block piece placed one level-2 sample off;
3. level 0 of base chunk 1 ([600, 1200) s: the 937 windows whose centre lies
   there, counted here) differs by more than 1e-5 relative from the same
   chunk computed here with `scipy.signal.csd` (Hann, 128 points, 64
   overlap) on the samples from the first of those windows to the end of
   the last, band-summed over f_lo <= f < f_hi and inverted: an
   independent path through the grid's placement in time, the centre rule,
   the conjugation and the band edges;
4. a group's Z misses the known one: at level 0 (937 windows a chunk) by
   more than 3 % of its modulus in any group (Zxy: chunks 0 and 1, the ones
   holding no window of the burst; windows belong to the chunk holding
   their centre, so chunks 2 and 4 each hold one straddling its edge),
   at level 1 (234) by more than 6 %, at level 2 (59) or level 3 (m = 2,
   groups of 28, 24 and a last of 14 windows) in the median over the groups
   by more than 15 % (level 3's Zxy: group 0 alone, the one group whose
   82 s windows miss the burst); the 1-sample delay turns Zxy's phase from
   -22 to -90 deg across level 0, where a conjugated cross-power or a
   swapped R/E shows. Level 4 (328 s windows, m = 5) must hold exactly one
   group, spanning the five chunks, with 12 windows (criterion 1's count)
   and its Zyx within 15 %. That group holds the burst (its Zxy is ~90 %
   off) and the 6 of its windows in L's first run give Zxy ~10-20 % off by
   chance alone, so level 4's Zxy is checked exactly instead: the stack of
   those 6 windows (all after 1500 s masked) must agree to 1e-4 relative
   with Z computed here by scipy.signal.decimate (x4, four times, FIR, zero
   phase, float64) of L's first run as generated and `scipy.signal.csd`
   over the same windows, an independent path through the stitched stream,
   the deep cascade, the level-4 grid and the band edges;
5. coh_xy in the burst chunk is not below 0.3 at every level-0 and level-1
   band while chunks 0 and 1 (no window of the burst) are above 0.8, or
   coh_yx in the burst chunk drops below 0.8 (chunks 2 and 4 are printed:
   one straddling window, 10 times Ex's rms over up to half its length,
   pulls level 1 there down to ~0.65);
6. `bin_windows` at 60 s, regrouped to 600 s, does not give the 600 s
   group sums (er, hr, eh, hh, ee, n_used, n_possible) to 1e-12 relative at
   the binned levels: levels 0 and 1 chunk by chunk (m = 1 at both lengths),
   level 2 (m = 3 at 60 s: 16 groups of 180 s and a partial last one of
   120 s, kept for its 11 grid windows) over [0, 1800) and [1800, 3000) s,
   where both grids have edges;
7. the unmasked stack is not identical at 60, 300 and 600 s chunks, or, on
   a store over the gap-free stretch [T0 + 120, T0 + 1380) s, its level-0 Z
   differs by more than 1e-6 relative from the one computed here with
   `scipy.signal.csd` over the samples from the first grid window to the
   end of the last (1967 windows, counted here);
8. a level whose smallest group exceeds the record (level 5: 18 chunks of
   600 s, the record 5) does not come back with empty arrays from
   `band_view` and `masked_chunks`, or `stack_impedance` raises on it;
   b. or such a level's kept windows are not all stacked: on the calm store
      ([T0 + 120, T0 + 1380) s, 2 chunks of 600 s) level 4 (m = 5) has no
      group but keeps 5 windows (the global grid's windows lying there that
      touch no gap, counted here with the stitched stream's ends, 56 s and
      1984 s, as gaps from level 3 on): `band_view` and `masked_chunks` must
      be empty, and at every level-4 band the stack's n_windows 5,
      n_chunks 0, its z finite and within 1e-4 relative of the one computed
      here (scipy.signal.decimate x4 four times of L's first run, csd over
      those 5 windows), its note naming the missing group; a 60 s mask
      [T0 + 600, T0 + 660) s must take exactly the windows it overlaps
      (3, counted here) from n_windows into n_windows_masked. A stack that
      reads only the display groups' windows gives n_windows 0 there;
9. a 60 s mask [T0 + 600, T0 + 660) s over the band of level 4 does not
   drop from the stack's n_windows exactly the kept level-4 windows it
   overlaps (counted here from criterion 1's windows: 3), report them as
   n_windows_masked, keep the group (n_chunks 1, n_masked 0) and make
   `masked_chunks` say 1 (partly) for it;
10. a read ever asks h5py for more than one block plus its two margins
    ((600 + 2 * 64) s = 72800 samples; L's runs are 150000 samples, so a
    whole-run load fails this), or the reads are not, in number and in
    samples, one per block, channel and run the block's read span meets
    (counted here from the five blocks' spans [600 k - 64, 600 k + 664) s
    and the runs: 34 reads, 2118400 samples; a second pass over the
    archives, for the stream levels or anything else, doubles both); or the
    read margin (`_margin_n`) is not 64 s at 100 Hz, or at 35 Hz, where the
    deepest binned window (level 2) is 2048 samples (58.5 s) and the
    cascade's FIR transient down to it 40 + 160 = 200 base samples (half
    of the 81-tap filter, 40 input samples, at levels 1 and 2), is under
    2248 samples (64 s rounded up to 16 samples is only 2240);
11. 3 workers give a store (every array, the stream) that is not identical
    to 1 worker's, or the tail rule is not: end = T0 + 2700 s gives 5
    chunks, the last ending at 2700 s; end = T0 + 2640 s gives 4, the 240 s
    tail joining the last (ending at 2640 s);
12. `stack_impedance` (every kept window's <E R*> times the inverse of the
    sum of their <H R*>, jackknifed over display groups) does not:
    a. with the burst chunk masked (bands all), reproduce the known Z within
       2 % at every level-0 and level-1 band (Zxy and Zyx) and within 8 % at
       levels 2 and 3, with n_chunks 4 and n_masked 1 at levels 0-2;
    b. show the burst when it is left in: Zxy's error must exceed the masked
       stack's at every level-0 and level-1 band and exceed 2 % in their
       median, Zyx (no burst) must stay within 2 %, and on 300 s chunks
       (10 display groups, 8 with the burst masked; 600 s leaves 4, under
       the jackknife's 5) Zxy's jackknife error must be larger with the
       burst in than out at every level-0 and level-1 band;
    c. with chunks 0 and 3 masked by time, agree to 1e-6 relative at level 0
       with the stack of the windows centred in chunks 1, 2 and 4 computed
       here with `scipy.signal.csd`: per run of consecutive kept windows
       (criterion 1's, split by L's gap and the masks) the band sums times
       the run's window count, all added, then inverted; an independent
       path through the window weighting, the conjugation and which windows
       a mask takes;
    d. act per band: a band mask over the burst chunk with one level-0
       band's [pmin, pmax] must give that band the burst-masked stack and
       every other band the unmasked one, identical, with n_masked 1 at
       that band and 0 elsewhere;
13. `stack_impedance`'s jackknife differs, on a hand-made store (`tiny_store`:
    1 Hz, one binned level, one band, one display group per minute bin, band
    sums drawn from a known Z), by more than 1e-12 relative from the
    delete-one-group formula written out here on 7 groups of 4 to 20
    windows, where the unweighted formula is 20 % off, so equal weights
    fail this. The formula: Z_(g) the stack without group g, n_g its
    windows, N their sum, h_g = N / n_g, the pseudo-values
    h_g Z - (h_g - 1) Z_(g) about theta = G Z - sum (1 - n_g / N) Z_(g),
    error sqrt(1/G sum |pseudo - theta|^2 / (h_g - 1)) per element (Busing,
    Meijer & van der Leeden 1999). Or it differs from the classical
    sqrt((G - 1) / G sum |Z_(g) - mean|^2) on 6 equal groups; or the error
    is not NaN, with the note "no jackknife: 4 display group(s), 5 needed",
    on 4 groups, or not finite on 5 (`MIN_GROUPS`);
14. a group keeping fewer than half its grid windows has an estimate: on a
    hand-made store whose groups keep 5, 6, 4, 3 and 8 of 11, 11, 8, 4 and 8
    grid windows, exactly groups 1, 2 and 4 must be finite (5 of 11 is under
    half; 3 is under `MIN_WINDOWS`; 4 of 8, exactly half, stands), with
    n_windows 0 at the others;
15. chunk 1's h_amp or e_amp at any level-0 band differs by more than 1e-5
    relative from the root of the band-mean of Hx's plus Hy's (Ex's plus
    Ey's) power density from `scipy.signal.welch` (Hann, 128 points, 64
    overlap) over the samples of its 937 windows, or its coh_xy or coh_yx
    from the coherence, over those windows and the band's harmonics, of E
    with the E that the csd Z (criterion 3's) predicts from H, each window's
    spectra from `scipy.signal.spectrogram` (mode complex, one-sided
    density weights); an independent path through the amplitude
    normalisation and the coherence;
16. the stitched stream's two ends do not count as gaps: a store over
    [T0 + 120, T0 + 1320) s (inside L's first run, two whole blocks, so the
    stream runs from the first block's read start at 56 s to the last one's
    read end at 1384 s and its ends are its only gaps) must keep, at levels
    3 and 4, exactly the windows counted here with those ends as level-2
    gaps; at level 4 that loses the first and the last of the 6 grid
    windows (153.6-481.3 s and 972.8-1300.5 s), which the FIR transient of
    an end reaches and which a stream without its ends as gaps keeps;
17. a range asked of `bin_windows` that starts and ends inside a minute
    ([T0 + 705, T0 + 1725) s) is not rounded out to whole minutes and
    reported so: ``start`` and ``end`` must be T0 + 660 s and T0 + 1740 s,
    the chunks start at 660 and 1260 s and the last ends at 1740 s; chunk 0
    at levels 0-2 must hold exactly the windows centred in [660, 1260) s
    (counted here from criterion 1's windows: none centred before the edge
    the result reports) and its er sum be that of the store's minute bins
    from 660 s to 1260 s (1e-12 relative), and level 3's one group exactly
    the kept windows lying inside [660, 1740) s. A result that labels the
    requested start while summing the whole first minute fails this.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from mth5.mth5 import MTH5
from mth5.timeseries import ChannelTS, RunTS
from scipy.signal import csd, decimate, spectrogram, welch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from loguru import logger  # noqa: E402

from crust.bands import build_band_scheme  # noqa: E402
from crust.crosspower import (  # noqa: E402
    MARGIN_S, MIN_GROUPS, SUMS, WindowStore, _margin_n, _plan_levels, band_view, bin_windows, chunk_impedances,
    compute_windows, level_multiples, masked_chunks, stack_impedance,
)
from crust.timefreq import MIN_WINDOWS  # noqa: E402

logger.remove()  # after mth5's import, which adds its own sink
logger.add(sys.stderr, level="WARNING")

FS = 100.0
T0 = pd.Timestamp("2023-09-22T00:00:00", tz="UTC")
LEAD_S, SPAN_S = 100.0, 3300.0  # the field runs from T0 - LEAD_S for SPAN_S
L_RUNS_S = [(0.0, 1500.0), (1600.0, 3100.0)]
CHUNK_S = 600.0
BURST = 3
Z_TRUE = {"xx": 0.3, "xy": 2.0, "yx": -1.5, "yy": -0.2}
DELAY = 1  # samples, on Zxy
SURVEY = "SYNTH"
SCHEME = build_band_scheme(FS)
RECORD_S = 3000.0  # the store's span after T0
STREAM_END_S = 3064.0  # the last block's read end: the stitched stream stops there
CALM_L4 = 5  # level-4 windows the calm store ([T0 + 120, T0 + 1380) s) keeps, counted here
minute_calm_s = (600.0, 660.0)  # a 60 s mask inside the calm store's level-4 windows
ENDS_S = (120.0, 1320.0)  # a store inside L's first run, two whole blocks: its stream's ends are its only gaps
MID_S = (705.0, 1725.0)  # a range asked of `bin_windows` that starts and ends inside a minute
G0 = int(T0.value // 10**7)  # T0 as a base-sample index from the epoch (100 Hz: 1e7 ns a sample)


def field_and_channels(seed: int = 5):
    """Generate the synthetic field and the six recorded channels.

    Args:
        seed (int): The random generator's seed.

    Returns:
        dict: {name: float64 samples on the field's grid, from T0 - LEAD_S}
        for L's ex, ey, hx, hy and R's r_hx, r_hy, as counts with a DC offset.
    """
    rng = np.random.default_rng(seed)
    n = int(SPAN_S * FS)
    hx, hy = 1000.0 * rng.standard_normal(n), 1000.0 * rng.standard_normal(n)
    ex = Z_TRUE["xx"] * hx + Z_TRUE["xy"] * np.roll(hy, DELAY)
    ey = Z_TRUE["yx"] * hx + Z_TRUE["yy"] * hy
    ex += 0.1 * ex.std() * rng.standard_normal(n)
    ey += 0.1 * ey.std() * rng.standard_normal(n)
    b0 = int((LEAD_S + BURST * CHUNK_S) * FS)
    ex[b0: b0 + int(CHUNK_S * FS)] += 10.0 * ex.std() * rng.standard_normal(int(CHUNK_S * FS))
    out = {"ex": ex, "ey": ey,
           "hx": hx + 300.0 * rng.standard_normal(n), "hy": hy + 300.0 * rng.standard_normal(n),
           "r_hx": hx + 300.0 * rng.standard_normal(n), "r_hy": hy + 300.0 * rng.standard_normal(n)}
    return {k: np.rint(v + 5e6) for k, v in out.items()}  # counts with a DC offset, as a logger's


def write_archive(path: Path, site: str, runs) -> None:
    """Write a site's runs as an MTH5 archive, laid out as `crust.ingest.ingest_site` lays a site out.

    Args:
        path (Path): The archive to write.
        site (str): The station.
        runs: [(start, {component: int32 counts})], one entry per run.
    """
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        for i, (start, comps) in enumerate(runs, 1):
            run_id = f"sr{int(FS)}_{i:04d}"
            chans = []
            for c, data in comps.items():
                kind = "electric" if c.startswith("e") else "magnetic"
                chans.append(ChannelTS(channel_type=kind, data=np.asarray(data, dtype="int32"),
                                       channel_metadata={kind: {"component": c, "sample_rate": FS,
                                                                "time_period.start": start.isoformat()}}))
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()


def index(t_s: float) -> int:
    """Return the field-grid index of T0 + t_s."""
    return int(round((t_s + LEAD_S) * FS))


def g(t_s: float) -> int:
    """Return the base-sample index (from the epoch) of T0 + t_s."""
    return G0 + int(round(t_s * FS))


def band_z(sums: dict) -> np.ndarray:
    """Return Z = <E R*> <H R*>^-1 from band sums keyed by (channel, remote channel)."""
    er = np.array([[sums[("ex", "r_hx")], sums[("ex", "r_hy")]], [sums[("ey", "r_hx")], sums[("ey", "r_hy")]]])
    hr = np.array([[sums[("hx", "r_hx")], sums[("hx", "r_hy")]], [sums[("hy", "r_hx")], sums[("hy", "r_hy")]]])
    return er @ np.linalg.inv(hr)


def expected(lo: float, hi: float, level: int) -> tuple[complex, complex]:
    """Return the true band-averaged Zxy and Zyx at one level: white H, so each harmonic weighs the same."""
    fs = FS / 4**level
    f = np.fft.rfftfreq(128, 1.0 / fs)
    f = f[(f >= lo) & (f < hi)]
    return Z_TRUE["xy"] * np.mean(np.exp(-2j * np.pi * f * DELAY / FS)), complex(Z_TRUE["yx"])


def csd_z(data: dict, runs, lo: float, hi: float) -> np.ndarray:
    """Return Z from scipy.signal.csd over runs of consecutive grid windows.

    Each run's band sums times its window count, added over the runs, then
    inverted.

    Args:
        data (dict): The channels as generated (`field_and_channels`).
        runs: [(first start, count)], starts in base samples.
        lo (float): The band's lower edge, Hz.
        hi (float): The band's upper edge, Hz (excluded).

    Returns:
        np.ndarray: Z [2, 2].
    """
    er, hr = np.zeros((2, 2), dtype=complex), np.zeros((2, 2), dtype=complex)
    for first, count in runs:
        a = first - g(-LEAD_S)
        sl = slice(a, a + 64 * (count - 1) + 128)
        for row, e in enumerate(("ex", "ey", "hx", "hy")):
            for col, r in enumerate(("r_hx", "r_hy")):
                f, pxy = csd(data[r][sl], data[e][sl], fs=FS, window="hann", nperseg=128, noverlap=64,
                             detrend="constant", scaling="density")  # csd(r, e) = <E R*>, the mean over windows
                total = count * pxy[(f >= lo) & (f < hi)].sum()
                (er if row < 2 else hr)[row % 2, col] += total
    return er @ np.linalg.inv(hr)


def runs_of(starts: np.ndarray, hop: int) -> list[tuple[int, int]]:
    """Return consecutive grid windows (starts `hop` apart) as [(first start, count)]."""
    if starts.size == 0:
        return []
    cut = np.flatnonzero(np.diff(starts) != hop) + 1
    return [(int(p[0]), int(p.size)) for p in np.split(starts, cut)]


def dilate(gaps):
    """Return the gaps one level down, dilated as `crust.timefreq.decimation_levels` dilates a gap."""
    out = []
    for a, b in sorted((a // 4 - 32, b // 4 + 1 + 32) for a, b in gaps):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def grid_here(n_levels: int, lo_s: float, hi_s: float, read_s=(-MARGIN_S, STREAM_END_S)):
    """Return, per level, the grid windows whose span lies in [lo_s, hi_s) and those touching no gap.

    Args:
        n_levels (int): Levels to count.
        lo_s (float): Start of the span, s after T0.
        hi_s (float): End of the span, s after T0.
        read_s (tuple): The first block's read start and the last block's
            read end (s after T0), where the stitched level-2 stream starts
            and stops; gaps for the stream levels (3 on) only.

    Returns:
        list: Per level, (every grid window start, the starts of those
        touching no gap), in global base samples.
    """
    far = 10**15
    gaps = [(-far, g(0.0)), (g(1500.0), g(1600.0)), (g(3100.0), far)]  # L's uncovered samples; R covers all
    ends = [(-far, g(read_s[0]) // 16), (g(read_s[1]) // 16, g(read_s[1]) // 16)]  # level-2 indices
    out = []
    for level in range(n_levels):
        if level > 0:
            gaps = dilate(gaps)
        if level == 3:  # the stitched stream is level 2: its ends are gaps from there down
            gaps = _union(gaps, dilate(ends))
        scale, win = 4**level, 128
        hop_b = 64 * scale
        lo, hi = g(lo_s), g(hi_s)
        starts = np.arange(-(-lo // hop_b), (hi - win * scale) // hop_b + 1, dtype=np.int64) * hop_b
        idx = starts // scale
        bad = np.zeros(starts.size, dtype=bool)
        for a, b in gaps:
            bad |= (idx < b) & (idx + win > a)
        out.append((starts, starts[~bad]))
    return out


def _union(a, b):
    """Return the union of two span lists, sorted and merged."""
    out = []
    for lo, hi in sorted(a + b):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def tiny_store(n_used, n_possible=None, seed: int = 11) -> WindowStore:
    """Return a hand-made `WindowStore` with one display group per minute bin.

    1 Hz, one binned level (16-point windows, hop 8, one band of 8 harmonics,
    so m = 1 at 60 s chunks), one item per minute bin from the epoch. Each
    window's band sums come from complex Gaussian H (2), R = H + noise and
    E = Z H + noise, Z = [[0.3, 2], [-1.5, -0.2]].

    Args:
        n_used: Windows kept per bin.
        n_possible: Grid windows per bin (default: n_used).
        seed (int): The random generator's seed.

    Returns:
        WindowStore: The store.
    """
    rng = np.random.default_rng(seed)
    n_used = np.asarray(n_used, dtype=np.int64)
    n_possible = n_used.copy() if n_possible is None else np.asarray(n_possible, dtype=np.int64)
    z = np.array([[Z_TRUE["xx"], Z_TRUE["xy"]], [Z_TRUE["yx"], Z_TRUE["yy"]]], dtype=complex)
    cn = lambda *shape: rng.standard_normal(shape) + 1j * rng.standard_normal(shape)  # noqa: E731
    sums = {name: [] for name in SUMS}
    for n in n_used:
        h = cn(n, 2)
        r, e = h + 0.5 * cn(n, 2), h @ z.T + 0.5 * cn(n, 2)
        outer = lambda a, b: np.einsum("wi,wj->ij", a, np.conj(b))[None]  # noqa: E731  [1 band, 2, 2]
        sums["er"].append(outer(e, r))
        sums["hr"].append(outer(h, r))
        sums["eh"].append(outer(e, h))
        sums["hh"].append(outer(h, h))
        sums["ee"].append((np.abs(e) ** 2).sum(axis=0)[None])
    level = {"level": 0, "binned": True, "win": 16, "win_b": 16, "hop_b": 8, "bands": np.array([0]),
             "n_harm": np.array([8]), "starts": np.arange(n_used.size, dtype=np.int64) * 60, "span_n": 60,
             "n_used": n_used, "n_possible": n_possible, **{k: np.array(v) for k, v in sums.items()}}
    return WindowStore("T", "TR", 1.0, 4, 0, 60 * n_used.size, 60, 0, np.array([0]), np.array([0.1]),
                       np.array([0.2]), [level], {}, 0, [], 600, 1, 0.0)


def kept_starts(store, level: int) -> np.ndarray:
    """Return the starts of the windows a stream level keeps (a binned level raises ValueError)."""
    lv = store.levels[level]
    if not lv["binned"]:
        return lv["starts"][lv["n_used"] > 0]
    raise ValueError("a binned level keeps sums per minute bin, not windows")


def main() -> int:
    """Build the archives and stores, check criteria 1-17 and print one line per criterion."""
    data = field_and_channels()
    reads: list[int] = []
    real_getitem = h5py.Dataset.__getitem__

    def recording(self, key):
        out = real_getitem(self, key)
        if isinstance(out, np.ndarray) and out.ndim == 1:
            reads.append(out.size)
        return out

    at = lambda s: T0 + pd.Timedelta(seconds=s)  # noqa: E731
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        local, remote = tmp / "L.h5", tmp / "R.h5"
        write_archive(local, "L", [(at(a), {c: data[c][index(a): index(b)] for c in ("ex", "ey", "hx", "hy")})
                                   for a, b in L_RUNS_S])
        write_archive(remote, "R", [(at(-LEAD_S), {"hx": data["r_hx"], "hy": data["r_hy"]})])
        h5py.Dataset.__getitem__ = recording
        try:
            store = compute_windows(local, "L", remote, "R", T0, at(RECORD_S), SCHEME, workers=1)
        finally:
            h5py.Dataset.__getitem__ = real_getitem
        store3 = compute_windows(local, "L", remote, "R", T0, at(RECORD_S), SCHEME, workers=3)
        calm = compute_windows(local, "L", remote, "R", at(120.0), at(1380.0), SCHEME, workers=2)
        ends = compute_windows(local, "L", remote, "R", at(ENDS_S[0]), at(ENDS_S[1]), SCHEME, workers=1)
        tail5 = chunk_impedances(local, "L", remote, "R", T0, at(2700.0), SCHEME, chunk_s=CHUNK_S)
        tail4 = chunk_impedances(local, "L", remote, "R", T0, at(2640.0), SCHEME, chunk_s=CHUNK_S)

    one = bin_windows(store, CHUNK_S)
    store_levels = _plan_levels(SCHEME, FS)[1]
    n_chunks, n_bands = one["zxy"].shape
    n_levels = len(store.levels)
    level_of = one["band_level"]
    assert n_chunks == 5 and n_bands == one["periods"].size, one["zxy"].shape
    multiples = [grid["multiple"] for grid in one["grids"]]
    assert multiples == level_multiples(SCHEME, FS, CHUNK_S) == [1, 1, 1, 2, 5, 18, 70, 280, 560], multiples
    print(f"  store: {n_chunks} chunks of 600 s x {n_bands} bands, binned levels 0-{store.binned_level}, multiples "
          f"{multiples}, {store.nbytes / 1e6:.2f} MB, {store.elapsed_s:.1f} s on 1 worker")

    # 1. the window grid tiles the record
    here = grid_here(n_levels, 0.0, RECORD_S)
    counts = []
    for level, (grid, clean) in enumerate(here):
        lv = store.levels[level]
        assert int(lv["n_possible"].sum()) == grid.size, (level, int(lv["n_possible"].sum()), grid.size)
        if lv["binned"]:  # per bin: the clean windows whose centre falls in it
            centre_bin = (clean + 64 * 4**level) // (60 * 100)
            want = np.bincount(centre_bin - lv["starts"][0] // 6000, minlength=lv["starts"].size)
            assert np.array_equal(lv["n_used"], want), (level, np.flatnonzero(lv["n_used"] != want))
        else:
            assert np.array_equal(kept_starts(store, level), clean), (level, kept_starts(store, level).size,
                                                                      clean.size)
        counts.append(f"{int(lv['n_used'].sum())}/{grid.size}")
        assert int(lv["n_used"].sum()) == clean.size, (level, int(lv["n_used"].sum()), clean.size)
    print(f"  1. kept / grid windows per level, as counted here: {', '.join(counts)}")

    # 2. the stitched stream against a continuous decimation of L's first run
    worst = 0.0
    a, b = index(0.0), index(1500.0)
    for c in ("ex", "ey", "hx", "hy"):
        cont = decimate(decimate(data[c][a:b] - np.median(data[c][a:b]), 4, ftype="fir", zero_phase=True),
                        4, ftype="fir", zero_phase=True)  # sample j at T0 + 16 j base samples
        j = np.arange(int(200.0 * FS / 16), int(1300.0 * FS / 16))
        mine = store.stream[c][(G0 + 16 * j - store.stream_start) // 16].astype(np.float64)
        ref = cont[j]
        err = np.max(np.abs((mine - np.median(mine)) - (ref - np.median(ref)))) / ref.std()
        worst = max(worst, err)
        assert err < 1e-4, (c, err)
    print(f"  2. stitched level-2 stream == scipy.signal.decimate of the continuous run to {worst:.1e} of its rms")

    # 3. level 0 of chunk 1 through scipy, windows by centre
    grid0, clean0 = here[0]
    in1 = clean0[(clean0 + 64 >= g(600.0)) & (clean0 + 64 < g(1200.0))]
    assert in1.size == 937 and runs_of(in1, 64) == [(int(in1[0]), 937)], in1.size
    worst = 0.0
    for j in np.flatnonzero(level_of == 0):
        z = csd_z(data, runs_of(in1, 64), one["band_lo_hz"][j], one["band_hi_hz"][j])
        got = band_view(one, j)["z"][1]
        err = np.max(np.abs(got - z)) / np.max(np.abs(z))
        worst = max(worst, err)
        assert err < 1e-5, (one["periods"][j], got, z)
        assert band_view(one, j)["n_windows"][1] == 937
    print(f"  3. chunk 1, level 0 ({in1.size} windows by centre): the tool and scipy.signal.csd agree to "
          f"{worst:.1e} relative")

    # 4. the known tensor per group
    others = [k for k in range(n_chunks) if k != BURST]
    # windows sit on the global grid and belong to the chunk holding their centre, so chunks 2 and 4
    # each hold a window straddling an edge of the burst (up to half a window of it): 0 and 1 hold none
    clear = [0, 1]
    worst = {level: 0.0 for level in range(5)}
    for j in range(n_bands):
        level = int(level_of[j])
        if level > 3:
            continue
        v = band_view(one, j)
        want_xy, want_yx = expected(one["band_lo_hz"][j], one["band_hi_hz"][j], level)
        assert (v["n_windows"] > 0).all(), (j, v["n_windows"])
        # level 3's groups: [0, 1200), [1200, 2400) (the burst) and [2400, 3000), whose first 82 s windows
        # still overlap the burst's last seconds: only group 0 misses it
        rows = clear if level <= 2 else [0]
        err_xy = np.abs(v["zxy"][rows] - want_xy) / abs(want_xy)
        err_yx = np.abs(v["zyx"] - want_yx) / abs(want_yx)
        if level <= 1:
            tol = 0.03 if level == 0 else 0.06
            assert err_xy.max() < tol and err_yx.max() < tol, (one["periods"][j], err_xy, err_yx)
            worst[level] = max(worst[level], err_xy.max(), err_yx.max())
        else:
            med = max(np.median(err_xy), np.median(err_yx))
            assert med < 0.15, (one["periods"][j], err_xy, err_yx)
            worst[level] = max(worst[level], med)
    four = np.flatnonzero(level_of == 4)
    burst_mask = {"start": at(BURST * CHUNK_S), "end": at((BURST + 1) * CHUNK_S), "bands": "all"}
    # level 4 here: L's first run decimated x4 four times with scipy (float64), csd over the kept level-4
    # windows lying inside it; the tool's stack of the same windows (everything after 1500 s masked)
    a, b = index(0.0), index(1500.0)
    deep_here = {}
    for c in ("ex", "ey", "hx", "hy", "r_hx", "r_hy"):
        x = data[c][a:b] - np.median(data[c][a:b])
        for _ in range(4):
            x = decimate(x, 4, ftype="fir", zero_phase=True)
        deep_here[c] = x  # sample j at base sample g(0) + 256 j

    def deep_z(runs, lo, hi):
        """Return Z from `deep_here` and scipy.signal.csd over runs of consecutive level-4 windows.

        `runs` is [(first start, count)]; each run's band sums times its
        window count are added over the runs, then inverted.
        """
        sums = {}
        for e in ("ex", "ey", "hx", "hy"):
            for r in ("r_hx", "r_hy"):
                total = 0.0
                for first, count in runs:
                    j0 = (first - g(0.0)) // 256
                    sl = slice(j0, j0 + 64 * (count - 1) + 128)
                    f, pxy = csd(deep_here[r][sl], deep_here[e][sl], fs=FS / 256, window="hann", nperseg=128,
                                 noverlap=64, detrend="constant", scaling="density")
                    total = total + count * pxy[(f >= lo) & (f < hi)].sum()
                sums[(e, r)] = total
        return band_z(sums)
    clean4 = here[4][1]
    run1 = clean4[clean4 + 128 * 256 <= g(1500.0)]
    first_run = stack_impedance(one, [{"start": at(1500.0), "end": at(RECORD_S), "bands": "all"}])
    worst4 = [0.0, 0.0]
    for j in four:
        v = band_view(one, j)
        want_xy, want_yx = expected(one["band_lo_hz"][j], one["band_hi_hz"][j], 4)
        assert v["multiple"] == 5 and len(v["starts"]) == 1 and v["starts"][0] == T0 and v["ends"][0] == at(RECORD_S)
        assert v["n_windows"][0] == clean4.size == 12, v["n_windows"]
        e_yx = abs(v["zyx"][0] - want_yx) / abs(want_yx)
        assert e_yx < 0.15, (one["periods"][j], e_yx)
        z = deep_z(runs_of(run1, 64 * 256), one["band_lo_hz"][j], one["band_hi_hz"][j])
        rel = np.max(np.abs(first_run["z"][j] - z)) / np.max(np.abs(z))
        assert rel < 1e-4 and first_run["n_windows"][j] == run1.size, (one["periods"][j], rel, first_run["n_windows"][j])
        worst4 = [max(worst4[0], e_yx), max(worst4[1], rel)]
    j_top = int(np.flatnonzero(level_of == 0)[0])
    phase_top = np.degrees(np.angle(expected(one["band_lo_hz"][j_top], one["band_hi_hz"][j_top], 0)[0]))
    print(f"  4. worst error: level 0 {100 * worst[0]:.1f} %, level 1 {100 * worst[1]:.1f} % (every group); "
          f"levels 2, 3 {100 * worst[2]:.1f}, {100 * worst[3]:.1f} % (median over groups); Zxy phase "
          f"{phase_top:.0f} deg at {one['periods'][j_top]:.3f} s; level 4, one group of 5 chunks, 12 windows: "
          f"Zyx {100 * worst4[0]:.1f} %; its {run1.size} windows in L's first run == scipy (decimate x4^4, csd) "
          f"to {worst4[1]:.1e} relative")

    # 5. the burst
    near = np.flatnonzero(level_of <= 1)
    assert (one["coh_xy"][BURST, near] < 0.3).all(), one["coh_xy"][BURST, near]
    assert (one["coh_xy"][np.ix_(clear, near)] > 0.8).all(), one["coh_xy"][np.ix_(clear, near)].min()
    assert (one["coh_yx"][BURST, near] > 0.8).all(), one["coh_yx"][BURST, near]
    print(f"  5. burst chunk coh_xy {one['coh_xy'][BURST, near].max():.2f} at most, others "
          f"{one['coh_xy'][np.ix_(clear, near)].min():.3f} at least in chunks 0-1 ("
          f"{one['coh_xy'][np.ix_([2, 4], near)].min():.2f} in 2 and 4, a straddling window each); coh_yx there "
          f"{one['coh_yx'][BURST, near].min():.3f} at least")

    # 6. 60 s chunks regrouped to 600 s
    sixty = bin_windows(store, 60.0)
    worst = 0.0

    def close(x, y):
        scale = max(np.max(np.abs(y)), 1e-300)
        return float(np.max(np.abs(x - y)) / scale)

    for level in range(store.binned_level + 1):
        s60, s600 = sixty["levels"][level], one["levels"][level]
        m60 = sixty["grids"][level]["multiple"]
        assert m60 == (1 if level <= 1 else 3), (level, m60)
        # groups of both grids between common edges: (60 s groups, 600 s groups) per stretch
        stretches = ([(range(10 * k, 10 * k + 10), [k]) for k in range(5)] if level <= 1
                     else [(range(0, 10), [0, 1, 2]), (range(10, 17), [3, 4])])
        if level == 2:  # 16 groups of 180 s and a partial last one of 120 s, kept (11 grid windows >= 4)
            assert len(sixty["grids"][2]["starts"]) == 17 and sixty["grids"][2]["ends"][-1] == at(RECORD_S)
            assert sixty["grids"][2]["starts"][-1] == at(2880.0), sixty["grids"][2]["starts"][-1]
        for g60, g600 in stretches:
            g60, g600 = list(g60), list(g600)
            for name in SUMS:
                err = close(s60["sums"][name][g60].sum(axis=0), s600["sums"][name][g600].sum(axis=0))
                worst = max(worst, err)
                assert err < 1e-12, (level, name, g60, g600, err)
            for name in ("n_used", "n_possible"):
                assert s60[name][g60].sum() == s600[name][g600].sum(), (level, name)
    print(f"  6. 60 s groups regrouped to 600 s: sums equal to {worst:.1e} relative at levels 0-{store.binned_level}")

    # 7. the unmasked stack whatever the chunk, and scipy on a gap-free stretch
    stacks = [stack_impedance(bin_windows(store, cs)) for cs in (60.0, 300.0, 600.0)]
    for key in ("z", "n_windows"):
        assert all(np.array_equal(s[key], stacks[2][key], equal_nan=True) for s in stacks), key
    starts_calm = grid_here(1, 120.0, 1380.0)[0][1]
    assert runs_of(starts_calm, 64) == [(int(starts_calm[0]), starts_calm.size)] and starts_calm.size == 1967, (
        starts_calm.size)
    calm_stack, calm_600 = stack_impedance(calm, chunk_s=60.0), stack_impedance(calm, chunk_s=600.0)
    assert np.array_equal(calm_stack["z"], calm_600["z"], equal_nan=True)
    worst = 0.0
    for j in np.flatnonzero(level_of == 0):
        z = csd_z(data, [(int(starts_calm[0]), starts_calm.size)], one["band_lo_hz"][j], one["band_hi_hz"][j])
        err = np.max(np.abs(calm_stack["z"][j] - z)) / np.max(np.abs(z))
        worst = max(worst, err)
        assert err < 1e-6, (one["periods"][j], err)
        assert calm_stack["n_windows"][j] == starts_calm.size, calm_stack["n_windows"][j]
    print(f"  7. unmasked stack identical at 60, 300 and 600 s chunks; on [120, 1380) s level 0 ({starts_calm.size} "
          f"windows) == scipy.signal.csd's to {worst:.1e} relative")

    # 8. a level whose smallest group exceeds the record
    five = np.flatnonzero(level_of == 5)
    full = stack_impedance(one)
    for j in five:
        v = band_view(one, j)
        assert len(v["starts"]) == 0 and v["z"].shape == (0, 2, 2) and v["n_windows"].size == 0, v["z"].shape
        assert masked_chunks(one, [burst_mask], j).size == 0
    assert all(full["notes"][j] for j in five), [full["notes"][j] for j in five]
    print(f"  8. level 5 (m 18 > 5 chunks): empty groups, masked_chunks empty, stack note "
          f"\"{full['notes'][five[0]]}\"")
    # 8b. a level with kept windows and no display group still stacks them: the calm store's level 4
    minute_calm = {"start": at(minute_calm_s[0]), "end": at(minute_calm_s[1]), "bands": "all"}
    calm_one = bin_windows(calm, CHUNK_S)
    calm4 = grid_here(5, 120.0, 1380.0, read_s=(120.0 - MARGIN_S, 1920.0 + MARGIN_S))[4][1]
    stored4 = calm.levels[4]["starts"][calm.levels[4]["n_used"] > 0]
    assert np.array_equal(stored4, calm4) and calm4.size == CALM_L4, (stored4.size, calm4.size)
    assert (calm4 + 128 * 256 <= g(1500.0)).all()  # inside L's first run, which deep_here holds
    worst8 = 0.0
    for j in four:
        v = band_view(calm_one, j)
        assert len(v["starts"]) == 0 and masked_chunks(calm_one, [minute_calm], j).size == 0, len(v["starts"])
        assert calm_600["n_windows"][j] == calm4.size and calm_600["n_chunks"][j] == 0, (
            calm_600["n_windows"][j], calm4.size)
        assert np.isfinite(calm_600["z"][j]).all() and "no display group" in calm_600["notes"][j], (
            calm_600["z"][j], calm_600["notes"][j])
        z = deep_z(runs_of(calm4, 64 * 256), one["band_lo_hz"][j], one["band_hi_hz"][j])
        rel = np.max(np.abs(calm_600["z"][j] - z)) / np.max(np.abs(z))
        worst8 = max(worst8, rel)
        assert rel < 1e-4, (one["periods"][j], rel)
        cut8 = stack_impedance(calm_one, [minute_calm])
        hit8 = int(((calm4 < g(minute_calm_s[1])) & (calm4 + 128 * 256 > g(minute_calm_s[0]))).sum())
        assert 0 < hit8 < calm4.size and cut8["n_windows"][j] == calm4.size - hit8, (hit8, cut8["n_windows"][j])
        assert cut8["n_windows_masked"][j] == hit8, cut8["n_windows_masked"][j]
    print(f"  8b. calm store, level 4 (m 5 > 2 chunks, no group): the stack takes all {calm4.size} kept windows "
          f"(counted here), z == scipy (decimate x4^4, csd) to {worst8:.1e}, note \"{calm_600['notes'][four[0]]}\"; "
          f"a 60 s mask takes {hit8} of them")

    # 9. a 60 s mask inside the level-4 group
    minute = {"start": at(600.0), "end": at(660.0), "bands": "all"}
    clean4 = here[4][1]
    hit_here = int(((clean4 < g(660.0)) & (clean4 + 128 * 256 > g(600.0))).sum())
    cut = stack_impedance(one, [minute])
    for j in four:
        assert cut["n_windows"][j] == full["n_windows"][j] - hit_here and cut["n_windows_masked"][j] == hit_here, (
            cut["n_windows"][j], full["n_windows"][j], hit_here)
        assert cut["n_chunks"][j] == 1 and cut["n_masked"][j] == 0, (cut["n_chunks"][j], cut["n_masked"][j])
        assert masked_chunks(one, [minute], j).tolist() == [1]
    assert hit_here == 3, hit_here
    print(f"  9. a 60 s mask in the level-4 group: {hit_here} of its {clean4.size} windows out (counted here), "
          f"the group kept, masked_chunks partly")

    # 10. streaming: every read within a block plus its margins, and each block read once
    limit = int((CHUNK_S + 2 * MARGIN_S) * FS)
    assert reads and max(reads) <= limit, (max(reads), limit)
    runs_l = [(g(a), g(b)) for a, b in L_RUNS_S]
    runs_r = [(g(-LEAD_S), g(SPAN_S - LEAD_S))]
    n_here = total_here = 0
    for k in range(int(RECORD_S // CHUNK_S)):
        r0, r1 = g(k * CHUNK_S - MARGIN_S), g((k + 1) * CHUNK_S + MARGIN_S)
        for runs, n_channels in ((runs_l, 4), (runs_r, 2)):
            for a, b in runs:
                over = min(b, r1) - max(a, r0)
                if over > 0:
                    n_here, total_here = n_here + n_channels, total_here + n_channels * over
    assert (len(reads), sum(reads)) == (n_here, total_here) == (34, 2118400), (len(reads), sum(reads), n_here,
                                                                               total_here)
    scheme35 = build_band_scheme(35.0)
    factor35, levels35 = _plan_levels(scheme35, 35.0)
    k35 = max(lv.level for lv in levels35 if lv.binned)
    margin35 = _margin_n(35.0, levels35, factor35, 4**k35)
    need35 = levels35[k35].win_b + sum(10 * 4 * 4 ** (step - 1) for step in range(1, k35 + 1))
    assert (k35, levels35[k35].win_b, need35) == (2, 2048, 2248) and margin35 >= need35 > 64 * 35, margin35
    assert _margin_n(FS, store_levels, 4, 16) == int(MARGIN_S * FS), _margin_n(FS, store_levels, 4, 16)
    print(f"  10. {len(reads)} h5py reads of {sum(reads)} samples, as counted here from the blocks and the runs "
          f"(one read per block, channel and run met); the largest {max(reads)} (limit {limit}; a run is 150000); "
          f"at 35 Hz the margin grows to {margin35} samples ({margin35 / 35:.2f} s) for a 2048-sample level-2 "
          f"window plus a 200-sample transient, at 100 Hz it stays {int(MARGIN_S * FS)}")

    # 11. workers and the tail
    for a_lv, b_lv in zip(store.levels, store3.levels):
        for key, value in a_lv.items():
            if isinstance(value, np.ndarray):
                assert np.array_equal(value, b_lv[key]), (a_lv["level"], key)
    for c in store.stream:
        assert np.array_equal(store.stream[c], store3.stream[c]), c
    assert tail5["zxy"].shape[0] == 5 and tail5["chunk_ends"][-1] == at(2700.0), (tail5["zxy"].shape,
                                                                                  tail5["chunk_ends"][-1])
    assert tail4["zxy"].shape[0] == 4 and tail4["chunk_ends"][-1] == at(2640.0), (tail4["zxy"].shape,
                                                                                  tail4["chunk_ends"][-1])
    print("  11. 3 workers identical to 1 (every store array, the stream); a 300 s tail kept as a fifth "
          "chunk, a 240 s one joining the fourth")

    # 12. the stacked estimate
    dirty, clean = full, stack_impedance(one, [burst_mask])
    fits = level_of <= 3
    near, deep = np.flatnonzero(level_of <= 1), np.flatnonzero((level_of >= 2) & fits)
    err = {}
    for name, s in (("clean", clean), ("dirty", dirty)):
        for mode in ("xy", "yx"):
            want = np.array([expected(one["band_lo_hz"][j], one["band_hi_hz"][j], int(level_of[j]))
                             [0 if mode == "xy" else 1] for j in range(n_bands)])
            with np.errstate(invalid="ignore"):
                err[(name, mode)] = np.abs(s[f"z{mode}"] - want) / np.abs(want)
    shallow = level_of <= 2
    assert (clean["n_chunks"][shallow] == 4).all() and (clean["n_masked"][shallow] == 1).all(), clean["n_chunks"]
    assert (dirty["n_chunks"][shallow] == 5).all() and (dirty["n_masked"] == 0).all(), dirty["n_chunks"]
    for mode in ("xy", "yx"):
        assert err[("clean", mode)][near].max() < 0.02, (mode, err[("clean", mode)][near])
        assert err[("clean", mode)][deep].max() < 0.08, (mode, err[("clean", mode)][deep])
    assert (err[("dirty", "xy")][near] > err[("clean", "xy")][near]).all(), (err[("dirty", "xy")][near],
                                                                             err[("clean", "xy")][near])
    assert np.median(err[("dirty", "xy")][near]) > 0.02, err[("dirty", "xy")][near]
    assert err[("dirty", "yx")][near].max() < 0.02, err[("dirty", "yx")][near]
    jk_dirty, jk_clean = stack_impedance(one, chunk_s=300.0), stack_impedance(one, [burst_mask], chunk_s=300.0)
    assert (jk_dirty["n_chunks"][near] == 10).all() and (jk_clean["n_chunks"][near] == 8).all()
    assert np.isfinite(dirty["zxy_err"][near]).all() and np.isnan(clean["zxy_err"][near]).all()  # 5, 4 groups
    assert (jk_dirty["zxy_err"][near] > jk_clean["zxy_err"][near]).all(), (jk_dirty["zxy_err"][near],
                                                                           jk_clean["zxy_err"][near])
    print(f"  12a. burst masked: stack within {100 * max(err[('clean', m)][near].max() for m in ('xy', 'yx')):.2f} % "
          f"at levels 0-1, {100 * max(err[('clean', m)][deep].max() for m in ('xy', 'yx')):.2f} % at levels 2-3")
    print(f"  12b. burst in: Zxy error median {100 * np.median(err[('dirty', 'xy')][near]):.1f} % "
          f"(max {100 * err[('dirty', 'xy')][near].max():.1f} %) at levels 0-1, above the masked stack's at every "
          f"band; Zyx {100 * err[('dirty', 'yx')][near].max():.2f} % at worst; Zxy jackknife on 300 s groups "
          f"{100 * np.median(jk_dirty['zxy_err'][near] / np.abs(jk_dirty['zxy'][near])):.1f} % vs "
          f"{100 * np.median(jk_clean['zxy_err'][near] / np.abs(jk_clean['zxy'][near])):.2f} % (medians); on "
          f"600 s the masked stack's 4 groups give \"{clean['notes'][near[0]]}\"")

    def chunk_mask(k, bands="all"):
        return {"start": one["chunk_starts"][k], "end": one["chunk_ends"][k], "bands": bands}

    kept = stack_impedance(one, [chunk_mask(k) for k in (0, BURST)])
    centre = clean0 + 64
    take = (((centre >= g(600.0)) & (centre < g(1800.0))) | ((centre >= g(2400.0)) & (centre < g(3000.0))))
    pieces = runs_of(clean0[take], 64)
    worst = 0.0
    for j in np.flatnonzero(level_of == 0):
        z = csd_z(data, pieces, one["band_lo_hz"][j], one["band_hi_hz"][j])
        rel = np.max(np.abs(kept["z"][j] - z)) / np.max(np.abs(z))
        worst = max(worst, rel)
        assert rel < 1e-6, (one["periods"][j], rel, kept["z"][j], z)
        assert kept["n_windows"][j] == sum(n for _s, n in pieces), (kept["n_windows"][j], pieces)
    print(f"  12c. chunks 1, 2, 4 kept (windows by centre, runs {[n for _s, n in pieces]}): stack == "
          f"scipy.signal.csd's to {worst:.1e} relative")

    j_band = int(np.flatnonzero(level_of == 0)[2])
    pmin, pmax = 1.0 / one["band_hi_hz"][j_band], 1.0 / one["band_lo_hz"][j_band]
    banded = stack_impedance(one, [chunk_mask(BURST, [pmin, pmax])])
    others_j = [j for j in range(n_bands) if j != j_band]
    assert np.array_equal(banded["z"][j_band], clean["z"][j_band]), (banded["z"][j_band], clean["z"][j_band])
    assert np.array_equal(banded["z"][others_j], dirty["z"][others_j], equal_nan=True)
    assert banded["n_masked"][j_band] == 1 and (banded["n_masked"][others_j] == 0).all(), banded["n_masked"]
    print(f"  12d. a band mask [{pmin:.4f}, {pmax:.4f}] s on the burst chunk: band {one['periods'][j_band]:.4f} s "
          f"takes the burst-masked stack, the other {len(others_j)} bands the unmasked one, identical")
    # 13. the jackknife against the delete-one-group formula written out here, and MIN_GROUPS
    def jackknife_here(er, hr, n):
        """Return (Z, its error per element) over groups with band sums er, hr [group, 2, 2] and n windows each.

        The delete-m_j jackknife for unequal groups (Busing, Meijer & van der
        Leeden 1999).
        """
        big_g, total = len(n), float(np.sum(n))
        s_er, s_hr = er.sum(axis=0), hr.sum(axis=0)
        z_all = s_er @ np.linalg.inv(s_hr)
        z_del = [(s_er - er[k]) @ np.linalg.inv(s_hr - hr[k]) for k in range(big_g)]  # Z without group k
        theta = big_g * z_all - sum((1.0 - n[k] / total) * z_del[k] for k in range(big_g))
        var = np.zeros((2, 2))
        for k in range(big_g):
            h = total / n[k]
            var += np.abs(h * z_all - (h - 1.0) * z_del[k] - theta) ** 2 / (h - 1.0)
        return z_all, np.sqrt(var / big_g)

    def classical_here(er, hr):
        """Return the equal-group jackknife error, sqrt((G - 1) / G sum |Z_(g) - mean Z_(g)|^2), per element."""
        big_g, s_er, s_hr = len(er), er.sum(axis=0), hr.sum(axis=0)
        z_del = np.array([(s_er - er[k]) @ np.linalg.inv(s_hr - hr[k]) for k in range(big_g)])
        return np.sqrt((big_g - 1) / big_g * np.sum(np.abs(z_del - z_del.mean(axis=0)) ** 2, axis=0))

    uneven_n = [4, 9, 6, 12, 5, 8, 20]
    uneven = tiny_store(uneven_n)
    got13 = stack_impedance(bin_windows(uneven, 60.0))
    lv13 = uneven.levels[0]
    z13, err13 = jackknife_here(lv13["er"][:, 0], lv13["hr"][:, 0], np.array(uneven_n, dtype=float))
    rel_z, rel_err = close(got13["z"][0], z13), close(got13["z_err"][0], err13)
    unweighted = close(classical_here(lv13["er"][:, 0], lv13["hr"][:, 0]), err13)
    assert got13["n_chunks"][0] == 7 and rel_z < 1e-12 and rel_err < 1e-12, (got13["n_chunks"], rel_z, rel_err)
    assert unweighted > 0.01, unweighted  # the group weights matter on this store: an unweighted formula fails
    even = tiny_store([8] * 6, seed=12)
    got_even = stack_impedance(bin_windows(even, 60.0))
    rel_even = close(got_even["z_err"][0], classical_here(even.levels[0]["er"][:, 0], even.levels[0]["hr"][:, 0]))
    assert rel_even < 1e-12, rel_even
    assert MIN_GROUPS == 5, MIN_GROUPS
    four_g = stack_impedance(bin_windows(tiny_store([6, 7, 8, 9], seed=13), 60.0))
    five_g = stack_impedance(bin_windows(tiny_store([6, 7, 8, 9, 10], seed=13), 60.0))
    assert np.isfinite(four_g["z"][0]).all() and np.isnan(four_g["z_err"][0]).all(), four_g["z_err"][0]
    assert four_g["notes"][0] == f"no jackknife: 4 display group(s), {MIN_GROUPS} needed", four_g["notes"][0]
    assert np.isfinite(five_g["z_err"][0]).all() and not five_g["notes"][0], (five_g["z_err"][0], five_g["notes"][0])
    print(f"  13. jackknife on a hand-made store of 7 groups ({uneven_n} windows): z and z_err == the delete-m_j "
          f"formula written out here to {max(rel_z, rel_err):.1e} (an unweighted formula is {100 * unweighted:.0f} % "
          f"off there); 6 equal groups == the classical formula to {rel_even:.1e}; 4 groups: NaN, "
          f"\"{four_g['notes'][0]}\"; 5 groups: finite")

    # 14. a group keeping fewer than half its grid windows (or fewer than MIN_WINDOWS) has no estimate
    used14, grid14 = [5, 6, 4, 3, 8], [11, 11, 8, 4, 8]
    half = bin_windows(tiny_store(used14, grid14, seed=14), 60.0)["levels"][0]
    finite14 = np.isfinite(half["z"][:, 0]).all(axis=(-2, -1))
    want14 = [n >= MIN_WINDOWS and n >= 0.5 * p for n, p in zip(used14, grid14)]
    assert finite14.tolist() == want14 == [False, True, True, False, True], (finite14, want14)
    assert (half["n_windows"][:, 0] == np.where(want14, used14, 0)).all(), half["n_windows"][:, 0]
    print(f"  14. groups keeping {used14} of {grid14} grid windows: estimates {finite14.tolist()} (5 of 11 under "
          f"half, 3 under {MIN_WINDOWS}; 4 of 8, exactly half, kept)")

    # 15. |H|, |E| and the coherences of chunk 1 (level 0) through scipy's welch and spectrogram
    first1, count1 = runs_of(in1, 64)[0]
    a15 = first1 - g(-LEAD_S)
    sl15 = slice(a15, a15 + 64 * (count1 - 1) + 128)
    chans = np.stack([data[c][sl15] for c in ("hx", "hy", "ex", "ey")])
    f_w, psd = welch(chans, fs=FS, window="hann", nperseg=128, noverlap=64, detrend="constant", scaling="density")
    f_s, _t, spec = spectrogram(chans, fs=FS, window="hann", nperseg=128, noverlap=64, detrend="constant",
                                mode="complex")  # [channel, harmonic, window]
    assert spec.shape[-1] == count1 == 937, spec.shape
    worst15 = {}
    for j in np.flatnonzero(level_of == 0):
        lo, hi = one["band_lo_hz"][j], one["band_hi_hz"][j]
        band_w, band_s = (f_w >= lo) & (f_w < hi), (f_s >= lo) & (f_s < hi)
        here15 = {"h_amp": np.sqrt(psd[:2][:, band_w].sum() / band_w.sum()),  # mean PSD of Hx + Hy over the band
                  "e_amp": np.sqrt(psd[2:][:, band_w].sum() / band_w.sum())}
        weight = np.where((f_s == 0) | (f_s == FS / 2), 1.0, 2.0)[band_s][:, None]  # one-sided density
        hx, hy, ex, ey = spec[:, band_s, :]
        z = csd_z(data, [(first1, count1)], lo, hi)
        for mode, row, e in (("coh_xy", 0, ex), ("coh_yx", 1, ey)):
            ep = z[row, 0] * hx + z[row, 1] * hy  # the E that Z predicts, window by window
            here15[mode] = (np.abs(np.sum(weight * e * np.conj(ep))) ** 2
                            / (np.sum(weight * np.abs(e) ** 2) * np.sum(weight * np.abs(ep) ** 2)))
        v = band_view(one, j)
        for key, value in here15.items():
            err = abs(v[key][1] - value) / abs(value)
            worst15[key] = max(worst15.get(key, 0.0), err)
            assert err < 1e-5, (one["periods"][j], key, v[key][1], value)
    print(f"  15. chunk 1, level 0: h_amp, e_amp == scipy.signal.welch's, coh_xy, coh_yx == the coherence of E with "
          f"Z H from scipy.signal.spectrogram's windows, to "
          f"{', '.join(f'{k} {e:.1e}' for k, e in worst15.items())} relative")

    # 16. the stitched stream's two ends are gaps: a store inside L's first run, whose only gaps they are
    read16 = (ENDS_S[0] - MARGIN_S, ENDS_S[1] + MARGIN_S)  # two whole blocks: the read span is the stream
    with_ends = grid_here(5, *ENDS_S, read_s=read16)
    no_ends = grid_here(5, *ENDS_S, read_s=(-1e6, 1e6))
    for level in (3, 4):
        assert np.array_equal(kept_starts(ends, level), with_ends[level][1]), (level, kept_starts(ends, level),
                                                                              with_ends[level][1])
    grid16, lost16 = with_ends[4][0], np.setdiff1d(no_ends[4][1], with_ends[4][1])
    assert no_ends[4][1].size == grid16.size == 6 and lost16.tolist() == [grid16[0], grid16[-1]], (
        no_ends[4][1].size, grid16, lost16)
    to_s = lambda n: (n - G0) / FS  # noqa: E731
    print(f"  16. store [{ENDS_S[0]:g}, {ENDS_S[1]:g}) s inside L's first run: level 4 keeps "
          f"{with_ends[4][1].size} of its {grid16.size} grid windows as counted here with the stream's ends "
          f"({read16[0]:g}, {read16[1]:g} s) as gaps, losing the first (from {to_s(grid16[0]):.2f} s) and the last "
          f"(to {to_s(grid16[-1]) + 327.68:.2f} s); level 3 as counted here too")

    # 17. a range starting and ending inside a minute is rounded out to whole minutes, and says so
    mid = bin_windows(store, CHUNK_S, at(MID_S[0]), at(MID_S[1]))
    edge0, edge1 = 660.0, 1740.0
    assert (mid["start"], mid["end"]) == (at(edge0), at(edge1)), (mid["start"], mid["end"])
    assert mid["chunk_starts"].tolist() == [at(edge0), at(1260.0)] and mid["chunk_ends"][-1] == at(edge1), (
        mid["chunk_starts"], mid["chunk_ends"])
    counts17 = []
    for level in range(store.binned_level + 1):  # windows by centre, counted here: none before the edge
        centre = here[level][1] + 64 * 4**level
        want = [int(((centre >= g(a)) & (centre < g(b))).sum()) for a, b in ((edge0, 1260.0), (1260.0, edge1))]
        assert mid["levels"][level]["n_used"].tolist() == want, (level, mid["levels"][level]["n_used"], want)
        counts17.append(want[0])
    lv0 = store.levels[0]
    bins0 = (lv0["starts"] >= g(edge0)) & (lv0["starts"] < g(1260.0))
    err17 = close(mid["levels"][0]["sums"]["er"][0], lv0["er"][bins0].sum(axis=0))
    assert err17 < 1e-12, err17
    deep17 = here[3][1]
    want3 = int(((deep17 >= g(edge0)) & (deep17 + 128 * 64 <= g(edge1))).sum())
    assert mid["grids"][3]["multiple"] == 2 and mid["levels"][3]["n_used"].tolist() == [want3], (
        mid["levels"][3]["n_used"], want3)
    print(f"  17. [{MID_S[0]:g}, {MID_S[1]:g}) s asked: covered and reported as [{edge0:g}, {edge1:g}) s, chunks from "
          f"{edge0:g} and 1260 s; chunk 0 sums {counts17} windows at levels 0-{store.binned_level}, all centred at or "
          f"after {edge0:g} s (counted here), level 3 its {want3} windows lying inside")
    print("\nPASS  crosspower_unit")
    return 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    raise SystemExit(main())
