"""Unit test for `bbmt.timefreq.psd_ladder` -- the whole-spectrum PSD ladder.

    python tests/psd_ladder_unit.py

**This test fails if** stage 0 of the ladder on random 1000 Hz arrays (three
channels, 30 min, two gaps) is not bit-identical (`numpy.array_equal`, freqs
and every channel's psd) to a direct `scipy.signal.welch` call with the same
parameters on the same gap-zeroed float64 samples -- which is what the moved
`scripts/psd_qc.py` code did; or the early stop does not follow the rule "a
stage runs while its array holds at least `min_segments * nperseg` samples":
a 30 min array must give exactly one stage with the default of 4 (1.8 M
samples at 1000 Hz, then 180 k at 100 Hz, under 4 x 65 536 = 262 144), a 1 h
array exactly two (3.6 M, 360 k, then 36 k) at the rates 1000 and 100 Hz,
and `min_segments=1` on the 30 min array exactly two (1.8 M and 180 k are
each at least 65 536, 18 k is not); or the ladder leaves NaN in a gap
instead of zero, does not cast the arrays it consumes to float64, or leaves
them at a length other than one decimation past the last stage computed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from scipy.signal import welch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bbmt.timefreq import PSD_NPERSEG, psd_ladder  # noqa: E402

FS = 1000.0
CHANNELS = ["hx", "hy", "ex"]
GAPS = [(200_000, 210_000), (1_500_000, 1_503_000)]


def arrays_for(minutes: float, seed: int = 7) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    n = int(minutes * 60 * FS)
    out = {}
    for c in CHANNELS:
        a = rng.standard_normal(n).astype("float32")
        for g0, g1 in GAPS:
            a[g0:g1] = np.nan  # NaN in the gaps, as a Record has them
        out[c] = a
    return out


def test_stage0_is_a_direct_welch() -> None:
    arrays = arrays_for(30)
    reference = {}
    for c in CHANNELS:
        x = arrays[c].copy()
        for g0, g1 in GAPS:
            x[g0:g1] = 0.0
        reference[c] = welch(
            x.astype("float64"), fs=FS, window="hann", nperseg=PSD_NPERSEG,
            detrend="constant", scaling="density",
        )
    stages = psd_ladder(arrays, list(GAPS), FS, CHANNELS)
    fs0, freqs, psd = stages[0]
    assert fs0 == FS
    for c in CHANNELS:
        f_ref, p_ref = reference[c]
        assert np.array_equal(freqs, f_ref), f"{c}: stage-0 freqs differ from welch"
        assert np.array_equal(psd[c], p_ref), f"{c}: stage-0 psd differs from welch"
    assert freqs.size == PSD_NPERSEG // 2 + 1
    print(f"  stage 0: {freqs.size} freqs, {CHANNELS} array_equal to scipy.signal.welch")


def test_early_stop_rule() -> None:
    stages = psd_ladder(arrays_for(30), list(GAPS), FS, CHANNELS)
    assert len(stages) == 1, f"30 min with min_segments=4 gave {len(stages)} stages, expected 1"
    stages = psd_ladder(arrays_for(60), list(GAPS), FS, CHANNELS)
    assert len(stages) == 2, f"1 h with min_segments=4 gave {len(stages)} stages, expected 2"
    assert [s[0] for s in stages] == [1000.0, 100.0], [s[0] for s in stages]
    stages = psd_ladder(arrays_for(30), list(GAPS), FS, CHANNELS, min_segments=1)
    assert len(stages) == 2, f"30 min with min_segments=1 gave {len(stages)} stages, expected 2"
    print("  early stop: 30 min -> 1 stage, 1 h -> 2 stages (default 4); 30 min, min_segments=1 -> 2")


def test_gaps_are_zeroed_and_arrays_consumed() -> None:
    arrays = arrays_for(30)
    stages = psd_ladder(arrays, list(GAPS), FS, CHANNELS)
    assert stages, "no stage"
    for c in CHANNELS:
        assert arrays[c].dtype == np.float64, f"{c}: not cast to float64 ({arrays[c].dtype})"
        assert not np.isnan(arrays[c]).any(), f"{c}: NaN survived the gap zeroing"
    # the last computed stage is followed by one decimation (arrays are consumed)
    assert arrays["hx"].size == int(30 * 60 * FS) // 10, arrays["hx"].size
    print("  gaps zeroed, arrays cast to float64 and consumed down one decimation")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  psd_ladder_unit ({len(tests)} tests)")
