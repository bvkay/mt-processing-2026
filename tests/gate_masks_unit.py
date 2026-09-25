# -*- coding: utf-8 -*-
"""
Unit test for scripts/gate_masks.py

Checks the night masks against hand-computed UTC windows, the burst
detector on a synthetic 1 Hz electric field, and the replacement of one
origin's masks in masks.yaml, on synthetic arrays and a temporary survey
folder. Runs without an archive.

The synthetic field is six hours of 1 Hz white noise (sd 10 counts) on ex
and ey with three bursts: square pulse trains of 2000 counts, 20 s on and
20 s off, on ey for 10 min from 01:00, on ex for 5 min from 03:00 and on
both for 15 min from 04:30.

Usage:
    python tests/gate_masks_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. the night masks of a record from 2023-07-22 13:16 to 2023-07-24 09:35 UTC
   with the window 01:00-05:00 Africa/Casablanca (UTC+1 in July) are not
   exactly [22 13:16, 23 00:00), [23 04:00, 24 00:00) and [24 04:00,
   24 09:35) UTC, all-band, found_by "night"; or the masks and the kept
   windows do not tile the record with no overlap; or a window across
   midnight (22:00-02:00, a record from 22 12:00 to 23 12:00 UTC) does not
   keep [22 21:00, 23 01:00) UTC alone; or a record that starts inside
   the window does not keep its first part;
2. the detector (K 3, M 60 s) does not flag every second from 60 s before
   each burst's first pulse to 60 s after the end of its last pulse, or
   flags any second more than 60 + 30 s from those pulses; or
   `second_spans` does not give exactly three spans; or K 1000 flags
   anything;
3. writing the night masks (`write_site_masks` with origin "night") does not
   leave the site's time, polar, cluster and gate masks equal to what they
   were and replace its earlier night mask, or writing gate masks touches
   the night ones;
4. a mutated detector passes: with M 0 criterion 2 must fail (the seconds
   before a burst's first pulse are then clear); the test runs the mutation
   and fails if criterion 2 still holds.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import gate_masks as gm  # noqa: E402
from crust.masks import load_masks, normalise, save_masks  # noqa: E402

T0 = pd.Timestamp("2023-07-22T00:00:00", tz="UTC")
BURSTS = [(3600, 600, (False, True)), (10800, 300, (True, False)), (16200, 900, (True, True))]  # start s, length s, (ex, ey)


def at(text: str) -> pd.Timestamp:
    """Return a UTC timestamp from text."""
    return pd.Timestamp(text, tz="UTC")


def field(seed: int = 2):
    """Return the synthetic 1 Hz ex, ey (module docstring) and each burst's [first pulse start, last pulse end) in s."""
    rng = np.random.default_rng(seed)
    n = 6 * 3600
    ex, ey = 10.0 * rng.standard_normal(n), 10.0 * rng.standard_normal(n)
    edges = []
    for s0, length, (on_x, on_y) in BURSTS:
        on = (np.arange(length) // 20) % 2 == 0
        pulse = 2000.0 * on
        if on_x:
            ex[s0: s0 + length] += pulse
        if on_y:
            ey[s0: s0 + length] += pulse
        edges.append((s0, s0 + int(np.flatnonzero(on)[-1]) + 1))
    return ex, ey, edges


def check_detector(burst, edges, m: int) -> None:
    """Criterion 2: burst seconds cover each burst's pulses widened by m s and nothing beyond m + 30 s."""
    for a, b in edges:
        lo, hi = max(0, a - m), min(burst.size, b + m)
        assert burst[lo:hi].all(), f"burst at {a} s: {int((~burst[lo:hi]).sum())} s of [{lo}, {hi}) not flagged"
    far = np.ones(burst.size, bool)
    for a, b in edges:
        far[max(0, a - m - 30): b + m + 30] = False
    assert not burst[far].any(), f"{int(burst[far].sum())} s flagged far from any burst"


def test_night() -> None:
    masks = gm.night_masks(at("2023-07-22T13:16"), at("2023-07-24T09:35"), "01:00-05:00", "Africa/Casablanca")
    spans = [(pd.Timestamp(m["start"]), pd.Timestamp(m["end"])) for m in masks]
    want = [(at("2023-07-22T13:16"), at("2023-07-23T00:00")), (at("2023-07-23T04:00"), at("2023-07-24T00:00")),
            (at("2023-07-24T04:00"), at("2023-07-24T09:35"))]
    assert spans == want, spans
    assert all(m["bands"] == "all" and m["found_by"] == "night" and normalise(m) == m for m in masks), masks
    kept = gm.night_windows(at("2023-07-22T13:16"), at("2023-07-24T09:35"), "01:00-05:00", "Africa/Casablanca")
    tiles = sorted(spans + kept)
    assert tiles[0][0] == at("2023-07-22T13:16") and tiles[-1][1] == at("2023-07-24T09:35"), tiles
    assert all(a[1] == b[0] for a, b in zip(tiles, tiles[1:])), tiles
    over = gm.night_windows(at("2023-07-22T12:00"), at("2023-07-23T12:00"), "22:00-02:00", "Africa/Casablanca")
    assert over == [(at("2023-07-22T21:00"), at("2023-07-23T01:00"))], over
    inside = gm.night_windows(at("2023-07-23T02:00"), at("2023-07-23T12:00"), "01:00-05:00", "Africa/Casablanca")
    assert inside == [(at("2023-07-23T02:00"), at("2023-07-23T04:00"))], inside
    print(f"  night: 01:00-05:00 Africa/Casablanca over 22 13:16 - 24 09:35 UTC -> masks {[(str(a), str(b)) for a, b in spans]}; "
          f"22:00-02:00 keeps 21:00-01:00 UTC; a record starting inside keeps its first part")


def test_detector() -> None:
    ex, ey, edges = field()
    burst, s = gm.burst_seconds(ex, ey, 3.0, 60)
    check_detector(burst, edges, 60)
    spans = gm.second_spans(burst, T0)
    assert len(spans) == 3, spans
    none, _s = gm.burst_seconds(ex, ey, 1000.0, 60)
    assert not none.any(), int(none.sum())
    print(f"  detector K 3 M 60: three spans {[(str(a.time()), str(b.time())) for a, b in spans]}, "
          f"{burst.mean():.1%} of 6 h flagged; K 1000 flags nothing")


def test_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")

        def mask(h0, h1, origin, bands="all"):
            return normalise({"start": T0 + pd.Timedelta(hours=h0), "end": T0 + pd.Timedelta(hours=h1),
                              "bands": bands, "reason": origin, "found_by": origin})

        others = [mask(0.5, 1.5, "time"), mask(2, 2.5, "polar", [0.2, 0.25]), mask(3, 3.5, "cluster", [0.3, 0.4]),
                  mask(4, 4.2, "gate")]
        save_masks(survey_yaml, "X", others + [mask(5, 6, "night")])
        night = gm.night_masks(T0, T0 + pd.Timedelta(days=1), "01:00-05:00", "UTC")
        kept, removed, written = gm.write_site_masks(survey_yaml, "X", night, "night")
        after = load_masks(survey_yaml, "X")
        assert (kept, removed, written) == (4, 1, len(night)), (kept, removed, written)
        assert sorted([m for m in after if m["found_by"] != "night"], key=str) == sorted(others, key=str), after
        assert sorted([m for m in after if m["found_by"] == "night"], key=str) == sorted(night, key=str), after
        gate = [mask(7, 7.1, "gate")]
        gm.write_site_masks(survey_yaml, "X", gate, "gate")
        after2 = load_masks(survey_yaml, "X")
        assert sorted([m for m in after2 if m["found_by"] == "night"], key=str) == sorted(night, key=str), after2
        assert [m for m in after2 if m["found_by"] == "gate"] == gate, after2
    print("  write: night masks replace the earlier night mask, time/polar/cluster/gate kept; a gate write leaves "
          "the night masks")


def test_mutation() -> None:
    ex, ey, edges = field()
    burst, _s = gm.burst_seconds(ex, ey, 3.0, 0)
    try:
        check_detector(burst, edges, 60)
    except AssertionError as exc:
        print(f"  mutation M 0: criterion 2 trips ({exc})")
    else:
        raise AssertionError("criterion 2 held with no widening of the bursts")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  gate_masks_unit ({len(tests)} tests)")
