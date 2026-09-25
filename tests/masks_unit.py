# -*- coding: utf-8 -*-
"""
Unit test for crust.masks

Checks masks.yaml (round trip, byte-stable blocks of other sites, duplicate
handling) and the cutting of time masks out of an mth5 `KernelDataset`
built from a synthetic frame. Runs without an archive.

Usage:
    python tests/masks_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. masks.yaml does not round-trip: two sites' masks saved one after the other
   (C23 with an all-bands and a band-limited mask, C10 with one) must load
   back equal to what was saved (normalised: UTC 'Z' times, earliest first,
   bands 'all' or [pmin, pmax] sorted), the file must keep its leading
   comment, and re-saving C23 with a different list must leave C10's block
   (and the header) unchanged in the file's text; saving C23 empty must
   remove its key and leave C10's bytes again; a hand-made C10 block with a
   comment line must survive a C23 save unchanged;
2. `apply_time_masks`, on a real mth5 `KernelDataset` built from a synthetic
   frame (local L, remote R, each one run 00:00-06:00 UTC), does not:
   split a run around a mask inside it into two rows per station with the
   bounds [00:00, 02:00) and [02:30, 06:00); trim a run whose mask covers its
   first 45 min to [00:45, 06:00); drop a run a mask covers whole (the other
   station's run then pairs with nothing and RR restriction raises -- tested
   in single-station form: the run's row goes and the other run's stays);
   drop a piece a mask leaves under 10 min (a mask 00:05-03:00 leaves
   [00:00, 00:05), which must go, and [03:00, 06:00)); or leave a run no mask
   touches exactly as it was;
3. a band-limited mask is applied (it must change nothing), or masks that
   leave nothing do not raise ValueError;
4. duplicates survive: the same interval and bands declared three times (a
   repeated click) must save as one entry and, written by hand into the
   file, must load as one; the same interval with other bands stays a
   separate mask.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from loguru import logger  # noqa: E402
from mth5.processing import KernelDataset  # noqa: E402

from crust.masks import HEADER, apply_time_masks, load_masks, masks_path, save_masks  # noqa: E402

logger.remove()  # after mth5's import, which adds its own sink
logger.add(sys.stderr, level="WARNING")

T0 = pd.Timestamp("2023-09-22T00:00:00", tz="UTC")


def at(hours: float) -> pd.Timestamp:
    """Return T0 plus a number of hours."""
    return T0 + pd.Timedelta(hours=hours)


def block_of(text: str, site: str) -> str:
    """Return the raw text of a site's block in masks.yaml.

    The block runs from the site's key line to the next unindented key line.

    Args:
        text (str): Text of masks.yaml.
        site (str): Site key.

    Returns:
        str: The block, or "" when the site has none.
    """
    lines = text.splitlines(keepends=True)
    out, inside = [], False
    for line in lines:
        top = line[:1] not in ("", " ", "-", "#", "\n")
        if top:
            inside = line.startswith(f"{site}:")
        if inside:
            out.append(line)
    return "".join(out)


def test_round_trip() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        c23 = [
            {"start": "2023-09-22 12:05:49", "end": "2023-09-22T12:25:49Z", "bands": "all",
             "reason": "mains switching", "found_by": "time"},
            {"start": at(1), "end": at(1.5), "bands": [0.1, 0.02], "reason": "polar outlier", "found_by": "polar"},
        ]
        c10 = [{"start": at(3), "end": at(3.25), "bands": "all", "reason": "", "found_by": "time"}]
        save_masks(survey_yaml, "C23", c23)
        save_masks(survey_yaml, "C10", c10)
        path = masks_path(survey_yaml)
        text = path.read_text(encoding="utf-8")
        assert text.startswith(HEADER), text[:200]
        got = load_masks(survey_yaml, "C23")
        want = [
            {"start": "2023-09-22T01:00:00Z", "end": "2023-09-22T01:30:00Z", "bands": [0.02, 0.1],
             "reason": "polar outlier", "found_by": "polar"},
            {"start": "2023-09-22T12:05:49Z", "end": "2023-09-22T12:25:49Z", "bands": "all",
             "reason": "mains switching", "found_by": "time"},
        ]
        assert got == want, got
        assert load_masks(survey_yaml, "C10")[0]["start"] == "2023-09-22T03:00:00Z"
        assert load_masks(survey_yaml, "C11") == []
        c10_bytes = block_of(text, "C10")
        assert c10_bytes, text

        save_masks(survey_yaml, "C23", c23[:1])
        text2 = path.read_text(encoding="utf-8")
        assert block_of(text2, "C10") == c10_bytes, (block_of(text2, "C10"), c10_bytes)
        assert text2.startswith(HEADER)
        assert len(load_masks(survey_yaml, "C23")) == 1

        save_masks(survey_yaml, "C23", [])
        text3 = path.read_text(encoding="utf-8")
        assert "C23" not in (yaml.safe_load(text3) or {}), text3
        assert block_of(text3, "C10") == c10_bytes
        print("  two sites round-trip; re-saving and emptying C23 leaves C10's block and the header unchanged")

        # a hand-edited block (a comment line inside, odd quoting) survives a save of another site
        hand = ("C10:\n# found by eye on the time series\n- {start: '2023-09-22T03:00:00Z', "
                "end: '2023-09-22T03:15:00Z', bands: all, reason: 'x', found_by: time}\n")
        path.write_text(HEADER + hand, encoding="utf-8")
        save_masks(survey_yaml, "C23", c23)
        text4 = path.read_text(encoding="utf-8")
        assert text4.startswith(HEADER + hand), text4
        assert len(load_masks(survey_yaml, "C23")) == 2
        print("  a hand-edited C10 block with a comment survives a C23 save unchanged")


def test_duplicates() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        polar = {"start": at(1), "end": at(1.5), "bands": [0.02, 0.1], "reason": "polar", "found_by": "polar"}
        other = {**polar, "bands": [1.0, 1.28]}
        save_masks(survey_yaml, "C20", [polar, polar, dict(polar), other])
        got = load_masks(survey_yaml, "C20")
        assert [m["bands"] for m in got] == [[0.02, 0.1], [1.0, 1.28]], got
        text = masks_path(survey_yaml).read_text(encoding="utf-8")
        assert text.count("found_by") == 2, text
        # the same three, written by hand
        hand = "".join("- {start: '2023-09-22T01:00:00Z', end: '2023-09-22T01:30:00Z', bands: [0.02, 0.1], "
                       "reason: 'x', found_by: polar}\n" for _ in range(3))
        masks_path(survey_yaml).write_text(HEADER + "C20:\n" + hand, encoding="utf-8")
        assert len(load_masks(survey_yaml, "C20")) == 1, load_masks(survey_yaml, "C20")
        print("  three identical masks save as one and load as one; the same interval with other bands stays")


def kernel(rows, remote: str | None = "R") -> KernelDataset:
    """Build a KernelDataset from (station, run, start, end) rows at 1000 Hz.

    Args:
        rows (list[tuple]): (station, run, start, end) per run.
        remote (str | None): Remote station id; local is "L".

    Returns:
        KernelDataset: Dataset with the frame set directly.
    """
    df = pd.DataFrame([{"survey": "S", "station": st, "run": run, "start": a, "end": b,
                        "sample_rate": 1000.0} for st, run, a, b in rows])
    kd = KernelDataset()
    kd.df = df
    kd.local_station_id = "L"
    kd.remote_station_id = remote
    return kd


def intervals(kd, station: str) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return a station's (start, end) rows of a KernelDataset, earliest first."""
    df = kd.df[kd.df.station == station].sort_values("start")
    return [(pd.Timestamp(a), pd.Timestamp(b)) for a, b in zip(df.start, df.end)]


def mask(a: float, b: float, bands="all") -> dict:
    """Build a time mask from hour a to hour b after T0."""
    return {"start": at(a), "end": at(b), "bands": bands, "reason": "", "found_by": "time"}


def test_apply() -> None:
    both = [("L", "a", at(0), at(6)), ("R", "b", at(0), at(6))]

    kd = apply_time_masks(kernel(both), [mask(2, 2.5)])
    for st in ("L", "R"):
        assert intervals(kd, st) == [(at(0), at(2)), (at(2.5), at(6))], (st, intervals(kd, st))
    assert set(kd.df.duration.round()) == {7200.0, 12600.0}, kd.df.duration.tolist()
    print("  a mask inside a run splits it into [00:00, 02:00) and [02:30, 06:00) on both stations")

    kd = apply_time_masks(kernel(both), [mask(-1, 0.75)])
    for st in ("L", "R"):
        assert intervals(kd, st) == [(at(0.75), at(6))], (st, intervals(kd, st))
    print("  a mask over a run's first 45 min trims it to [00:45, 06:00)")

    two = [("L", "a", at(0), at(3)), ("L", "c", at(4), at(6))]
    kd = apply_time_masks(kernel(two, remote=None), [mask(3.5, 7)])
    assert intervals(kd, "L") == [(at(0), at(3))], intervals(kd, "L")
    print("  a mask covering a run drops it; the untouched run stays as it was")

    kd = apply_time_masks(kernel(both), [mask(5 / 60, 3)])
    for st in ("L", "R"):
        assert intervals(kd, st) == [(at(3), at(6))], (st, intervals(kd, st))
    print("  the 5 min piece a mask leaves is dropped, [03:00, 06:00) kept")

    kd = apply_time_masks(kernel(both), [mask(2, 2.5, bands=[0.02, 0.1])])
    for st in ("L", "R"):
        assert intervals(kd, st) == [(at(0), at(6))], (st, intervals(kd, st))
    print("  a band-limited mask changes nothing here (it is applied by the band patch in crust.process)")

    try:
        apply_time_masks(kernel(both), [mask(-1, 7)])
    except ValueError as exc:
        assert "no data" in str(exc), exc
    else:
        raise AssertionError("masks covering everything did not raise")
    print("  masks that leave nothing raise ValueError")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  masks_unit ({len(tests)} tests)")
