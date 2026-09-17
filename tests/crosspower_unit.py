"""Unit test for `mtproc.crosspower.chunk_impedances` and `stack_impedance` on synthetic MTH5 archives.

    python tests/crosspower_unit.py

A local station L (ex ey hx hy) and a remote R (hx hy) at 100 Hz, int32
counts, written as real MTH5 archives the way `tests/virtual_unit.py` writes
its members (RunTS / `from_runts`, no filters, so every response is 1).
One white "field" pair Hx, Hy runs from T0 - 100 s to T0 + 3200 s; L records
it in two runs, [T0, T0 + 1500 s) and [T0 + 1600 s, T0 + 3100 s) (a 100 s
gap), R in one run over the whole span. L's coils add their own noise
(0.3 of the field rms: a single-station estimate would come out ~8 % low),
R's coils theirs (0.3), and L's electrics are

    Ex = 0.3 Hx + 2.0 Hy(t - 1 sample) + noise,   Ey = -1.5 Hx - 0.2 Hy + noise

(noise 0.1 of their rms), so the band's Zxy is 2 <exp(-2 pi i f / 100)> over
its harmonics, Zyx -1.5. Chunk 3 ([1800, 2400) s) adds a burst to Ex alone:
white noise 10 times its rms, which Hx, Hy do not predict. **This test fails if**

1. a chunk's Z misses the known one: on level 0 (936 STFT windows a chunk)
   by more than 3 % of its modulus in any chunk (Zxy: any but the burst
   chunk), on level 1 (233 windows) by more than 6 %, or, on levels 2 and 3
   (57 and 13 windows, whose chunk-to-chunk scatter is 3-10 %), in the median
   over the chunks by more than 15 %. The 1-sample delay turns Zxy's phase
   from -22 to -90 deg across level 0 (6-25 Hz), which is where a conjugated
   cross-power or a swapped R/E shows; the single-station bias (~8 % low)
   cannot pass level 0's 3 %. Or n_windows is 0 for a band whose level fits
   four STFT windows in a 600 s chunk, or not 0 for one whose level does not;
2. level 0 of chunk 1 (wholly inside L's first run) differs by more than
   1e-4 relative from the same chunk computed HERE with
   `scipy.signal.csd` (Hann, 128 points, 64 overlap) on the samples sliced
   from the generated arrays by time alone, band-summed over f_lo <= f < f_hi
   and inverted -- an independent path through the chunk's placement in
   time, the conjugation and the band edges;
3. chunk 2 (holding L's gap, samples 30000-40000 of the chunk) does not
   report, at level 0, exactly the number of 128-point, 64-hop windows that
   do not touch the gap, counted HERE (the full chunk has 936);
4. coh_xy in the burst chunk is not below 0.3 at every level-0 and level-1
   band while every other chunk's is above 0.8, or coh_yx in the burst chunk
   drops below 0.8 (the burst is on Ex only; L's own coil noise, 0.3 of the
   field, puts the clean value near 1 / 1.09 / 1.01 = 0.91);
5. a read ever asks h5py for more than one chunk plus its two margins
   ((600 + 2 * 64) s = 72800 samples): L's runs are 150000 samples, so a
   whole-run load cannot pass;
6. 3 workers give arrays different from 1 worker's (bit for bit), or the
   tail rule is not: end = T0 + 2700 s gives 5 chunks, the last ending at
   2700 s; end = T0 + 2640 s gives 4;
7. `stack_impedance` (Z = sum of the kept chunks' <E R*> times the inverse
   of the sum of their <H R*>, jackknifed over chunks) does not:
   a. with the burst chunk masked (bands all), reproduce the known Z within
      2 % at every level-0 and level-1 band (Zxy and Zyx; measured 1.7 % at
      worst) and within 8 % at levels 2 and 3 (57 and 13 windows a chunk,
      four chunks; measured 6.6 % at worst);
   b. show the burst when it is left in: Zxy's error must exceed the masked
      stack's at every level-0 and level-1 band and exceed 2 % in their
      median (measured 5.5 %; the burst chunk's Ex noise, 10 times Ex's rms,
      enters the sum), Zyx (no burst) must stay within 2 %, and Zxy's
      jackknife error must be larger with the burst in than out at every
      level-0 and level-1 band;
   c. with chunks 0 and 3 masked by time, agree to 1e-5 relative at level 0
      with the stack of chunks 1, 2 and 4 computed HERE with
      `scipy.signal.csd` on the generated samples: per gap-free piece of a
      chunk (chunk 2 is two, either side of L's gap) the band sums times
      the piece's window count, counted HERE (936, 467 + 311, 936), all
      added, then inverted -- an independent path through the window
      weighting (chunk 2 weighs 778/936 of the others; equal weights miss by
      2.7e-4, a mean of the chunks' Z by 3.0e-4), the conjugation and which chunks a mask takes;
   d. act per band: a band mask over the burst chunk with one level-0
      band's [pmin, pmax] must give that band the burst-masked stack and
      every other band the unmasked one, bit for bit, with n_masked 1 at
      that band and 0 elsewhere.
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
from scipy.signal import csd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from loguru import logger  # noqa: E402

from mtproc.bands import lemimt_band_scheme  # noqa: E402
from mtproc.crosspower import MARGIN_S, chunk_impedances, stack_impedance  # noqa: E402

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
SCHEME = lemimt_band_scheme(FS)


def field_and_channels(seed: int = 5):
    """{name: float64 samples on the field's grid (T0 - LEAD_S onwards)} for L's four and R's two."""
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
    """[(start, {component: int32 counts})] as `mtproc.ingest.ingest_site` lays a site out."""
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
    """The field-grid index of T0 + t_s."""
    return int(round((t_s + LEAD_S) * FS))


def band_z(sums: dict) -> np.ndarray:
    er = np.array([[sums[("ex", "r_hx")], sums[("ex", "r_hy")]], [sums[("ey", "r_hx")], sums[("ey", "r_hy")]]])
    hr = np.array([[sums[("hx", "r_hx")], sums[("hx", "r_hy")]], [sums[("hy", "r_hx")], sums[("hy", "r_hy")]]])
    return er @ np.linalg.inv(hr)


def expected(lo: float, hi: float, level: int) -> tuple[complex, complex]:
    """The true band-averaged Zxy and Zyx: white H, so each harmonic weighs the same."""
    fs = FS / 4**level
    f = np.fft.rfftfreq(128, 1.0 / fs)
    f = f[(f >= lo) & (f < hi)]
    return Z_TRUE["xy"] * np.mean(np.exp(-2j * np.pi * f * DELAY / FS)), complex(Z_TRUE["yx"])


def main() -> int:
    data = field_and_channels()
    reads: list[int] = []
    real_getitem = h5py.Dataset.__getitem__

    def recording(self, key):
        out = real_getitem(self, key)
        if isinstance(out, np.ndarray) and out.ndim == 1:
            reads.append(out.size)
        return out

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        local, remote = tmp / "L.h5", tmp / "R.h5"
        write_archive(local, "L", [(T0 + pd.Timedelta(seconds=a),
                                    {c: data[c][index(a): index(b)] for c in ("ex", "ey", "hx", "hy")})
                                   for a, b in L_RUNS_S])
        write_archive(remote, "R", [(T0 - pd.Timedelta(seconds=LEAD_S),
                                     {"hx": data["r_hx"], "hy": data["r_hy"]})])
        end = T0 + pd.Timedelta(seconds=3000)
        h5py.Dataset.__getitem__ = recording
        try:
            one = chunk_impedances(local, "L", remote, "R", T0, end, SCHEME, chunk_s=CHUNK_S, workers=1)
        finally:
            h5py.Dataset.__getitem__ = real_getitem
        three = chunk_impedances(local, "L", remote, "R", T0, end, SCHEME, chunk_s=CHUNK_S, workers=3)
        tail5 = chunk_impedances(local, "L", remote, "R", T0, T0 + pd.Timedelta(seconds=2700), SCHEME,
                                 chunk_s=CHUNK_S)
        tail4 = chunk_impedances(local, "L", remote, "R", T0, T0 + pd.Timedelta(seconds=2640), SCHEME,
                                 chunk_s=CHUNK_S)

    n_chunks, n_bands = one["zxy"].shape
    assert n_chunks == 5 and n_bands == one["periods"].size, one["zxy"].shape
    print(f"  {n_chunks} chunks x {n_bands} bands, {one['levels']} levels fit a chunk, "
          f"{one['elapsed_s']:.1f} s on 1 worker")

    # 1. the known tensor
    fits = one["band_level"] < one["levels"]
    others = [k for k in range(n_chunks) if k != BURST]
    worst = {0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0}
    for j in np.flatnonzero(fits):
        level = int(one["band_level"][j])
        want_xy, want_yx = expected(one["band_lo_hz"][j], one["band_hi_hz"][j], level)
        assert (one["n_windows"][:, j] > 0).all(), (j, one["n_windows"][:, j])
        err_xy = np.abs(one["zxy"][others, j] - want_xy) / abs(want_xy)
        err_yx = np.abs(one["zyx"][:, j] - want_yx) / abs(want_yx)
        if level <= 1:
            tol = 0.03 if level == 0 else 0.06
            assert err_xy.max() < tol and err_yx.max() < tol, (one["periods"][j], err_xy, err_yx)
            worst[level] = max(worst[level], err_xy.max(), err_yx.max())
        else:
            med = max(np.median(err_xy), np.median(err_yx))
            assert med < 0.15, (one["periods"][j], err_xy, err_yx)
            worst[level] = max(worst[level], med)
    assert (one["n_windows"][:, ~fits] == 0).all()
    j_top = int(np.flatnonzero(fits)[0])
    phase_top = np.degrees(np.angle(expected(one["band_lo_hz"][j_top], one["band_hi_hz"][j_top], 0)[0]))
    print(f"  1. worst error: level 0 {100 * worst[0]:.1f} %, level 1 {100 * worst[1]:.1f} % (every chunk); "
          f"levels 2, 3 {100 * worst[2]:.1f}, {100 * worst[3]:.1f} % (median over chunks); Zxy phase "
          f"{phase_top:.0f} deg at {one['periods'][j_top]:.3f} s; {int((~fits).sum())} bands longer than a "
          f"chunk left at n_windows 0")

    # 2. level 0 of chunk 1 through scipy, on samples sliced by time alone
    a = index(1 * CHUNK_S)
    sl = slice(a, a + int(CHUNK_S * FS))
    names = {"ex": "ex", "ey": "ey", "hx": "hx", "hy": "hy", "r_hx": "r_hx", "r_hy": "r_hy"}
    worst = 0.0
    for j in np.flatnonzero(one["band_level"] == 0):
        lo, hi = one["band_lo_hz"][j], one["band_hi_hz"][j]
        sums = {}
        for e in ("ex", "ey", "hx", "hy"):
            for r in ("r_hx", "r_hy"):
                f, pxy = csd(data[names[r]][sl], data[names[e]][sl], fs=FS, window="hann", nperseg=128,
                             noverlap=64, detrend="constant", scaling="density")
                sel = (f >= lo) & (f < hi)
                sums[(e, r)] = pxy[sel].sum()  # csd(r, e) = <E R*>
        z = band_z(sums)
        got = one["z"][1, j]
        err = np.max(np.abs(got - z)) / np.max(np.abs(z))
        worst = max(worst, err)
        assert err < 1e-4, (one["periods"][j], got, z)
    print(f"  2. chunk 1, level 0: the tool and scipy.signal.csd agree to {worst:.1e} relative")

    # 3. the gap's windows
    gap = (int((1500.0 - 2 * CHUNK_S) * FS), int((1600.0 - 2 * CHUNK_S) * FS))
    starts = np.arange(0, int(CHUNK_S * FS) - 128 + 1, 64)
    clean = int(((starts + 128 <= gap[0]) | (starts >= gap[1])).sum())
    level0 = np.flatnonzero(one["band_level"] == 0)
    assert (one["n_windows"][2, level0] == clean).all(), (one["n_windows"][2, level0], clean)
    assert (one["n_windows"][1, level0] == starts.size).all(), (one["n_windows"][1, level0], starts.size)
    print(f"  3. chunk 2 keeps {clean} of {starts.size} level-0 windows around L's gap, as counted here")

    # 4. the burst
    near = np.flatnonzero(one["band_level"] <= 1)
    assert (one["coh_xy"][BURST, near] < 0.3).all(), one["coh_xy"][BURST, near]
    assert (one["coh_xy"][np.ix_(others, near)] > 0.8).all(), one["coh_xy"][np.ix_(others, near)].min()
    assert (one["coh_yx"][BURST, near] > 0.8).all(), one["coh_yx"][BURST, near]
    print(f"  4. burst chunk coh_xy {one['coh_xy'][BURST, near].max():.2f} at most, others "
          f"{one['coh_xy'][np.ix_(others, near)].min():.3f} at least; coh_yx there "
          f"{one['coh_yx'][BURST, near].min():.3f} at least")

    # 5. streaming
    limit = int((CHUNK_S + 2 * MARGIN_S) * FS)
    assert reads and max(reads) <= limit, (max(reads), limit)
    print(f"  5. {len(reads)} h5py reads, the largest {max(reads)} samples (limit {limit}; a run is 150000)")

    # 6. workers and the tail
    for key in ("z", "coh_xy", "coh_yx", "n_windows", "h_amp", "e_amp"):
        assert np.array_equal(one[key], three[key], equal_nan=True), key
    assert tail5["zxy"].shape[0] == 5 and tail5["chunk_ends"][-1] == T0 + pd.Timedelta(seconds=2700), \
        (tail5["zxy"].shape, tail5["chunk_ends"][-1])
    assert tail4["zxy"].shape[0] == 4, tail4["zxy"].shape
    print("  6. 3 workers bit-identical to 1; a 300 s tail kept as a fifth chunk, a 240 s one dropped")

    # 7. the stacked estimate
    def chunk_mask(k, bands="all"):
        return {"start": one["chunk_starts"][k], "end": one["chunk_ends"][k], "bands": bands}

    clean, dirty = stack_impedance(one, [chunk_mask(BURST)]), stack_impedance(one)
    near, deep = np.flatnonzero(fits & (one["band_level"] <= 1)), np.flatnonzero(fits & (one["band_level"] >= 2))
    err = {}
    for name, s in (("clean", clean), ("dirty", dirty)):
        for mode in ("xy", "yx"):
            want = np.array([expected(one["band_lo_hz"][j], one["band_hi_hz"][j], int(one["band_level"][j]))
                             [0 if mode == "xy" else 1] for j in range(n_bands)])
            with np.errstate(invalid="ignore"):
                err[(name, mode)] = np.abs(s[f"z{mode}"] - want) / np.abs(want)
    assert (clean["n_chunks"][fits] == 4).all() and (clean["n_masked"][fits] == 1).all(), clean["n_chunks"]
    assert (dirty["n_chunks"][fits] == 5).all() and (dirty["n_masked"] == 0).all(), dirty["n_chunks"]
    for mode in ("xy", "yx"):
        assert err[("clean", mode)][near].max() < 0.02, (mode, err[("clean", mode)][near])
        assert err[("clean", mode)][deep].max() < 0.08, (mode, err[("clean", mode)][deep])
    assert (err[("dirty", "xy")][near] > err[("clean", "xy")][near]).all(), (err[("dirty", "xy")][near],
                                                                             err[("clean", "xy")][near])
    assert np.median(err[("dirty", "xy")][near]) > 0.02, err[("dirty", "xy")][near]
    assert err[("dirty", "yx")][near].max() < 0.02, err[("dirty", "yx")][near]
    assert (dirty["zxy_err"][near] > clean["zxy_err"][near]).all(), (dirty["zxy_err"][near], clean["zxy_err"][near])
    print(f"  7a. burst masked: stack within {100 * max(err[('clean', m)][near].max() for m in ('xy', 'yx')):.2f} % "
          f"at levels 0-1, {100 * max(err[('clean', m)][deep].max() for m in ('xy', 'yx')):.2f} % at levels 2-3")
    print(f"  7b. burst in: Zxy error median {100 * np.median(err[('dirty', 'xy')][near]):.1f} % "
          f"(max {100 * err[('dirty', 'xy')][near].max():.1f} %) at levels 0-1, above the masked stack's at every "
          f"band; Zyx {100 * err[('dirty', 'yx')][near].max():.2f} % at worst; Zxy jackknife "
          f"{100 * np.median(dirty['zxy_err'][near] / np.abs(dirty['zxy'][near])):.1f} % vs "
          f"{100 * np.median(clean['zxy_err'][near] / np.abs(clean['zxy'][near])):.2f} % (medians)")

    kept = stack_impedance(one, [chunk_mask(k) for k in (0, BURST)])
    n_chunk = int(CHUNK_S * FS)
    assert gap[1] % 64 == 0  # the windows after L's gap sit on the chunk's 64-sample hop grid
    pieces = {1: [(0, n_chunk)], 2: [(0, gap[0]), (gap[1], n_chunk)], 4: [(0, n_chunk)]}
    count = lambda a, b: (b - a - 128) // 64 + 1  # full 128-point windows, 64 apart, in [a, b)
    n_pieces = {k: [count(a, b) for a, b in v] for k, v in pieces.items()}
    worst = 0.0
    for j in np.flatnonzero(one["band_level"] == 0):
        lo, hi = one["band_lo_hz"][j], one["band_hi_hz"][j]
        er_sum, hr_sum = np.zeros((2, 2), dtype=complex), np.zeros((2, 2), dtype=complex)
        for k, spans in pieces.items():
            for a, b in spans:
                sl = slice(index(k * CHUNK_S) + a, index(k * CHUNK_S) + b)
                for row, e in enumerate(("ex", "ey", "hx", "hy")):
                    for col, r in enumerate(("r_hx", "r_hy")):
                        f, pxy = csd(data[r][sl], data[e][sl], fs=FS, window="hann", nperseg=128, noverlap=64,
                                     detrend="constant", scaling="density")
                        total = count(a, b) * pxy[(f >= lo) & (f < hi)].sum()  # csd is the mean over windows
                        if row < 2:
                            er_sum[row, col] += total
                        else:
                            hr_sum[row - 2, col] += total
        z = er_sum @ np.linalg.inv(hr_sum)
        rel = np.max(np.abs(kept["z"][j] - z)) / np.max(np.abs(z))
        worst = max(worst, rel)
        assert rel < 1e-5, (one["periods"][j], rel, kept["z"][j], z)
        assert kept["n_windows"][j] == sum(map(sum, n_pieces.values())), (kept["n_windows"][j], n_pieces)
    print(f"  7c. chunks 1, 2, 4 kept ({n_pieces} windows): stack == scipy.signal.csd's to {worst:.1e} relative")

    j_band = int(np.flatnonzero(one["band_level"] == 0)[2])
    pmin, pmax = 1.0 / one["band_hi_hz"][j_band], 1.0 / one["band_lo_hz"][j_band]
    banded = stack_impedance(one, [chunk_mask(BURST, [pmin, pmax])])
    others_j = [j for j in range(n_bands) if j != j_band]
    assert np.array_equal(banded["z"][j_band], clean["z"][j_band]), (banded["z"][j_band], clean["z"][j_band])
    assert np.array_equal(banded["z"][others_j], dirty["z"][others_j], equal_nan=True)
    assert banded["n_masked"][j_band] == 1 and (banded["n_masked"][others_j] == 0).all(), banded["n_masked"]
    print(f"  7d. a band mask [{pmin:.4f}, {pmax:.4f}] s on the burst chunk: band {one['periods'][j_band]:.4f} s "
          f"takes the burst-masked stack, the other {len(others_j)} bands the unmasked one, bit for bit")
    print("\nPASS  crosspower_unit")
    return 0


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    raise SystemExit(main())
