# -*- coding: utf-8 -*-
"""
Unit test for the time chunks of mt_workbench.noise's mains filter

`mains_subtract` given a thread pool, and `apply_filters_arrays(chunk_workers=N)`
as `build_variant` calls it, against the single pass and against a stored
result of the single pass before the pool was added (a937bc4,
tests/fixtures/noise_chunks/mains_single_pass_a937bc4.npz). The synthetic is
30 min at 1000 Hz per channel: an offset of 5e4 counts and a drift, a 50 Hz
mains with its 3rd and 5th harmonics whose amplitude steps from 100 to 300
at 600.0031 s and back at 1300.0117 s, and white noise of 1 rms (seeds 0-3
for ex, ey, hx, hy).

The stored result holds, per channel, the SHA-256 of the float64 output of
`mains_subtract` and of `apply_filters_arrays` with mains then notch, the
steps, and the sum and largest |sample| per 10,000-sample block (to show
where and by how much an output differs). It was made on this machine's
bbmt-2026 environment from a git archive of a937bc4; another numpy or BLAS
build may round differently and need it remade from that tree.

Usage:
    python tests/noise_chunks_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the single pass of `mains_subtract` on any channel,
or `apply_filters_arrays` with mains then notch, is not bit for bit the
stored a937bc4 result (so a change shared by the single pass and the pool
shows); `mains_subtract` over an 8-thread pool is not bit for bit the
single pass (samples and steps), or fewer than 30 chunk calls reach the
pool; a 5 min record over the pool is not bit for bit the single pass; or
`apply_filters_arrays` with chunk_workers=8 does not give the same
provenance lines and the same output, bit for bit, as chunk_workers=1, for
mains and for mains then notch.
"""

from __future__ import annotations

import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mt_workbench.noise import apply_filters_arrays, mains_subtract  # noqa: E402

FS = 1000.0
N = int(30 * 60 * FS)
STEPS = (600.0031, 1300.0117)
COMPS = ("ex", "ey", "hx", "hy")
BLOCK = 10_000
MAINS = {"mains": {"f0": 50.0, "harmonics": 9, "block_s": 1.0, "step_fraction": 0.3}}
NOTCH = {"notch": {"f0": 50.0, "harmonics": 9, "q": 30.0, "passes": 2}}
REFERENCE = Path(__file__).resolve().parent / "fixtures" / "noise_chunks" / "mains_single_pass_a937bc4.npz"


class CountingPool(ThreadPoolExecutor):
    """A thread pool that counts the calls submitted to it."""

    def __init__(self, workers: int):
        super().__init__(workers)
        self.calls = 0

    def submit(self, fn, /, *args, **kwargs):
        self.calls += 1
        return super().submit(fn, *args, **kwargs)


def synthetic(seed: int) -> np.ndarray:
    """Return one channel of the synthetic of the module docstring, as float64."""
    t = np.arange(N) / FS
    theta = 2 * np.pi * (49.98 * t + 0.04 * t ** 2 / (2 * 1800.0))
    amp = np.where((t >= STEPS[0]) & (t < STEPS[1]), 300.0, 100.0)
    mains = amp * (np.cos(theta + 0.3) + np.cos(3 * theta + 1.1) + np.cos(5 * theta + 2.0))
    rng = np.random.default_rng(seed)
    return 5e4 + 20.0 * np.sin(2 * np.pi * t / 900.0) + mains + rng.standard_normal(N)


def sha(y: np.ndarray) -> str:
    """Return the SHA-256 of y as little-endian float64 bytes."""
    return hashlib.sha256(np.ascontiguousarray(y, dtype="<f8").tobytes()).hexdigest()


def blocks(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the sum and the largest |sample| of each BLOCK-sample block."""
    b = np.asarray(y, dtype="float64").reshape(-1, BLOCK)
    return b.sum(axis=1), np.abs(b).max(axis=1)


def against_reference(ref, key: str, y: np.ndarray, what: str) -> None:
    """Assert y is bit for bit the stored result `key`, naming the blocks that differ when not."""
    if sha(y) == str(ref[f"{key}_sha256"]):
        return
    s, m = blocks(y)
    ds, dm = np.abs(s - ref[f"{key}_block_sum"]), np.abs(m - ref[f"{key}_block_max"])
    bad = np.flatnonzero((ds > 0) | (dm > 0))
    first = int(bad[0]) * BLOCK if len(bad) else "-"
    raise AssertionError(
        f"{what}: not bit for bit the a937bc4 single pass; {len(bad)} of {len(s)} blocks differ "
        f"(first at sample {first}), largest block-sum change {ds.max():.3g}, "
        f"largest block-max change {dm.max():.3g}")


def check_reference(raw: dict[str, np.ndarray], ref) -> None:
    for c in COMPS:
        y, info = mains_subtract(raw[c], FS)
        against_reference(ref, f"{c}_mains", y, f"mains {c}")
        stored = ref[f"{c}_mains_steps"]
        assert np.array_equal(info["steps"], stored), f"mains {c}: steps {info['steps']} != stored {stored}"
    print(f"reference: the single pass of mains_subtract == the stored a937bc4 result bit for bit "
          f"on {len(COMPS)} channels (SHA-256 and steps)")
    out, _lines = apply_filters_arrays(raw, FS, [MAINS, NOTCH], workers=4, chunk_workers=8)
    for c in COMPS:
        against_reference(ref, f"{c}_mains_notch", out[c], f"mains then notch {c}")
    print("reference: apply_filters_arrays mains then notch, chunk_workers 8 == the stored a937bc4 "
          "result bit for bit on 4 channels")


def check_mains(x: np.ndarray) -> None:
    single, info = mains_subtract(x, FS)
    with CountingPool(8) as pool:
        chunked, info_c = mains_subtract(x, FS, pool=pool)
    assert np.array_equal(chunked, single), "mains: chunked != single pass"
    assert np.array_equal(info_c["steps"], info["steps"]) and info_c["offset_mean"] == info["offset_mean"], \
        f"mains: steps {info_c['steps']} != {info['steps']}"
    assert len(info["steps"]) == 2, f"mains: the synthetic's two steps not found: {info['steps']}"
    assert pool.calls >= 30, f"mains: only {pool.calls} chunk calls reached the pool"
    print(f"mains: 8 threads == single pass bit for bit, steps {info['steps'].tolist()}, "
          f"{pool.calls} chunk calls over the pool")

    short = x[: int(300 * FS)]
    with ThreadPoolExecutor(8) as pool:
        assert np.array_equal(mains_subtract(short, FS, pool=pool)[0], mains_subtract(short, FS)[0]), \
            "mains: 5 min record"
    print("short: a 5 min record over the pool == single pass bit for bit")


def check_arrays(raw: dict[str, np.ndarray]) -> None:
    for filters in ([MAINS], [MAINS, NOTCH]):
        kinds = [next(iter(f)) for f in filters]
        one, lines_one = apply_filters_arrays(raw, FS, filters, workers=4, chunk_workers=1)
        many, lines_many = apply_filters_arrays(raw, FS, filters, workers=4, chunk_workers=8)
        assert lines_many == lines_one, f"provenance differs: {lines_many} != {lines_one}"
        for c in raw:
            assert np.array_equal(many[c], one[c]), f"{c}: {kinds} chunk_workers 8 != 1"
        print(f"apply_filters_arrays {kinds}: chunk_workers 8 == 1 bit for bit, the same lines")


def main() -> int:
    """Run every check and return 0 (a failure raises AssertionError)."""
    print(__doc__.split("**This test")[1].split('"""')[0].strip())
    print()
    raw = {c: synthetic(seed) for seed, c in enumerate(COMPS)}
    with np.load(REFERENCE) as ref:
        check_reference(raw, ref)
    check_mains(raw["ex"])
    check_arrays(raw)
    print("\nPASS  noise_chunks_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
