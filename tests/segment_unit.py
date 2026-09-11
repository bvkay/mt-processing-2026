"""Unit test for `bbmt_gui.segment` -- the segment QC engine on a synthetic hour, no Qt.

    python tests/segment_unit.py

The segment is 1 h at 1000 Hz, four channels: hx a 50 Hz sine of 1 nT
amplitude plus white noise (1 nT rms), hy the same samples plus independent
noise a tenth as large, ex independent noise, ey 0.3 hx plus noise, and one
10 s gap at 30 min. **This test fails if**

- `psd_ladder` stage 0 (the native rate) does not show the 50 Hz line on hx
  with `line_excess` above 20 dB over its local floor, or stage 1 is missing
  (a 1 h array supports stages 0 and 1);
- the band coherence hx-hy in the 0.01-0.1 s band (10-100 Hz) does not have a
  median above 0.95, or hy-ex -- the independent pair among the QC pairs
  (`LOCAL_PAIRS` has no hx-ex; hy is hx plus a tenth of its noise) -- does
  not have a median below 0.3;
- the spectrogram grid of hx has no finite values, has fewer than 20 time
  columns, or has NaN in more than a fifth of its columns (only the windows
  touching the 10 s gap may be dropped);
- `compute_segment_qc` changes any input array (SHA-1 of every channel's
  bytes, local and remote, before and after) or the gap list;
- `run_slices` (the run arithmetic `load_segment` shares with the Time Series
  tab's reads) does not place two runs with a gap between them at the right
  grid samples: run 1 at grid 0, run 2 at `round((start2 - t0) * fs)`, and a
  window across the gap gets exactly the two overlaps with the gap between
  them uncovered;
- a remote segment starting a whole sample off the local one is not refused.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bbmt.timefreq import line_excess  # noqa: E402
from bbmt_gui.archive import Grid, run_slices  # noqa: E402
from bbmt_gui.segment import Segment, compute_segment_qc  # noqa: E402

FS = 1000.0
N = int(3600 * FS)
GAP = (1_800_000, 1_810_000)  # 10 s at 30 min
T0 = pd.Timestamp("2021-06-29 07:25:49+00:00")


def synthetic(seed: int = 3) -> Segment:
    rng = np.random.default_rng(seed)
    t = np.arange(N) / FS
    hx = np.sin(2 * np.pi * 50.0 * t) + rng.standard_normal(N)
    hy = hx + 0.1 * rng.standard_normal(N)
    ex = rng.standard_normal(N)
    ey = 0.3 * hx + rng.standard_normal(N)
    arrays = {}
    for comp, a in (("hx", hx), ("hy", hy), ("ex", ex), ("ey", ey)):
        a = a.astype("float32")
        a[GAP[0] : GAP[1]] = 0.0
        arrays[comp] = a
    return Segment(
        station="SYN", survey="synthetic", t0=T0, sample_rate=FS, n=N, arrays=arrays,
        offsets={c: 0.0 for c in arrays}, gains={c: 1.0 for c in arrays},
        scalar_only={"hx", "hy"}, gaps=[GAP],
    )


def digests(segment: Segment) -> dict[str, str]:
    return {c: hashlib.sha1(a.tobytes()).hexdigest() for c, a in segment.arrays.items()}


def test_segment_qc() -> None:
    seg = synthetic()
    before, gaps_before = digests(seg), list(seg.gaps)
    remote = synthetic(seed=11)  # a second station: another draw of the same design
    remote.station = "RSYN"
    remote_before = digests(remote)
    messages = []
    qc = compute_segment_qc(seg, remote, progress=lambda p, m: messages.append((p, m)))
    assert digests(seg) == before and seg.gaps == gaps_before, "the local segment was modified"
    assert digests(remote) == remote_before, "the remote segment was modified"
    assert messages and messages[-1][0] == 100, messages
    print(f"  inputs unchanged; {len(messages)} progress calls, last {messages[-1]}")

    assert qc.channels == ["hx", "hy", "ex", "ey", "r_hx", "r_hy"], qc.channels
    assert len(qc.psd_stages) == 2, f"{len(qc.psd_stages)} PSD stages, expected 2 for 1 h"
    fs0, freqs, psd = qc.psd_stages[0]
    assert fs0 == FS and set(psd) == set(qc.channels)
    excess = line_excess(freqs, psd["hx"], 50.0)
    assert excess > 20.0, f"hx 50 Hz line excess {excess:.1f} dB, expected > 20"
    print(f"  psd stage 0: hx 50 Hz line {excess:+.1f} dB over the floor; stage 1 at {qc.psd_stages[1][0]:g} Hz")

    t, coh = qc.band_curves[("hx", "hy")]["0.01-0.1 s"]
    med_hxhy = float(np.nanmedian(coh))
    _, coh2 = qc.band_curves[("hy", "ex")]["0.01-0.1 s"]
    med_hyex = float(np.nanmedian(coh2))
    assert med_hxhy > 0.95, f"hx-hy 0.01-0.1 s median coherence {med_hxhy:.3f}, expected > 0.95"
    assert med_hyex < 0.3, f"hy-ex 0.01-0.1 s median coherence {med_hyex:.3f}, expected < 0.3"
    _, coh_r = qc.band_curves[("hx", "r_hx")]["0.01-0.1 s"]
    print(f"  band coherence 0.01-0.1 s: hx-hy {med_hxhy:.3f}, hy-ex {med_hyex:.3f}, "
          f"hx-r_hx {float(np.nanmedian(coh_r)):.3f} (independent draws), {t.size} columns")

    t_s, periods, db = qc.spectrograms["hx"]
    assert np.isfinite(db).any(), "hx spectrogram is all NaN"
    assert t_s.size >= 20 and db.shape[0] == t_s.size, f"{t_s.size} time columns"
    nan_cols = int((~np.isfinite(db)).all(axis=1).sum())
    assert nan_cols <= 0.2 * t_s.size, f"{nan_cols}/{t_s.size} columns NaN"
    assert periods.size == db.shape[1] and np.all(np.diff(periods) > 0)
    print(f"  hx spectrogram: {t_s.size} columns x {periods.size} periods "
          f"({periods.min():.4g}-{periods.max():.4g} s), {nan_cols} columns dropped at the gap; "
          f"plan {len(qc.plan)} levels, base window {qc.win_s:g} s step {qc.step_s:g} s")
    for pair in qc.pairs:
        _, per, img = qc.coherograms[pair]
        assert np.isfinite(img).any() and img.shape == (t_s.size, per.size), pair


def test_remote_off_grid_is_refused() -> None:
    seg = synthetic()
    remote = synthetic(seed=5)
    remote.t0 = T0 + pd.Timedelta(milliseconds=1)  # a whole sample late
    try:
        compute_segment_qc(seg, remote)
    except ValueError as exc:
        print(f"  refused: {exc}")
    else:
        raise AssertionError("a remote one sample off the local grid was accepted")


class _FakeStation(dict):
    """{run_id: {comp: array}} standing in for an h5py station group."""


def test_run_slices_places_runs() -> None:
    fs = 1000.0
    t0 = pd.Timestamp("2021-06-29 06:55:49+00:00")
    run1 = np.arange(5000, dtype="int32")  # 5 s from t0
    run2 = np.arange(7000, dtype="int32") + 100_000  # 7 s, starting 2.001 s after run 1 ends
    start2 = t0 + pd.Timedelta(milliseconds=7001)
    grid = Grid(
        path=Path("fake.h5"), station="X", survey="s", t0=t0, sample_rate=fs, n_samples=14001,
        group="/g", runs=[("r1", t0, t0), ("r2", start2, start2)], gains={"ex": 1.0},
        scalar_only=set(),
    )
    station = _FakeStation(r1={"ex": run1}, r2={"ex": run2})
    got = [(dst, src) for _ds, dst, src in run_slices(grid, station, "ex", 4000, 5000)]
    assert got == [
        (slice(0, 1000), slice(4000, 5000)),  # run 1's last second
        (slice(3001, 5000), slice(0, 1999)),  # run 2 from grid sample 7001
    ], got
    out = np.full(5000, np.nan)
    for ds, dst, src in run_slices(grid, station, "ex", 4000, 5000):
        out[dst] = ds[src]
    assert out[999] == 4999 and np.isnan(out[1000:3001]).all() and out[3001] == 100_000, out[[999, 1000, 3000, 3001]]
    assert grid.index_of(start2) == 7001 and grid.index_of("2021-06-29 06:55:50") == 1000
    print("  run_slices: run 1 at grid 0, run 2 at 7001, the 2.001 s between them uncovered")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  segment_unit ({len(tests)} tests)")
