# -*- coding: utf-8 -*-
"""
Unit test for the window a clipped MANTLE run takes

Checks `crust.mantle_window` (`covered_spans`, `choose_window`,
`clip_text`) on synthetic run intervals, and the way scripts/process_rr.py
uses it: `--mantle-window clip` in the resolution, the window and
`window_clipped` in the sidecar, the option refused with aurora, and the
default `refuse` leaving the resolution and the sidecar as they were. No
archive is read and no engine runs: `crust.engine_mantle.archive_spans` is
replaced by the synthetic spans where process_rr would read them.

Usage:
    python tests/mantle_window_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. `covered_spans` does not join two runs of an hour at 1000 Hz, the second
   starting on the sample after the first ends (or 0.4 ms later), into one
   span of 2 h, or joins them when the second starts 2 ms late;
2. two records covering a 19 h overlap without a gap, under a 24 h cap, do
   not give exactly that overlap with `clipped` None;
3. a 68 h overlap under a 48 h cap does not give its first 48 h (from the
   later record start) with {requested_hours 68, used_hours 48, reason
   "cap"}, or the window's length exceeds the cap by any amount (a start of
   1.7e9 s + 0.1 s must still give (end - start) / 3600 <= 48, which
   `check_window` compares);
4. a 1.5 h gap at 10-11.5 h in the local's record, both records 0-30 h,
   does not give the 18.5 h after the gap with reason "gap" and requested
   30 h; with the records running to 70 h and a 48 h cap, not the first
   48 h after the gap with reason "cap and gap"; with the gap at 30-31 h of
   50 h records and a 40 h cap, not the 30 h before the gap with reason
   "gap" (the cap cut nothing); with the gap at 50-51 h of 70 h records and
   a 24 h cap, not the first 24 h with reason "cap" alone (the gap lies
   beyond the window and moved nothing);
5. runs that differ between the sites (the local's gap at 20-21 h, the
   remote's at 15-16 h, both 0-40 h) do not give the 19 h from 21 h, the
   longest span both cover;
6. a pair whose common covered span is 0.5 h, or none, is not refused with
   ValueError naming the hour it needs (or the missing overlap); a start
   and end given (10-20 h of 70 h records) are not kept as they are;
7. process_rr.py's default is not refuse: a MANTLE resolution without the
   flag and one with `--mantle-window refuse` do not print the same lines,
   with no `mantle.window` line, and their sidecars do not carry the window
   given ({start None, end None}) and no `window_clipped` key, or their
   last lines are not exactly "mantle.whiten: none" and "mantle.max_hours:
   6", as before the option existed; with
   `--mantle-window clip` the resolution does not add `mantle.window: clip`,
   `choose_mantle_window` over synthetic spans (64.7 h, cap 6 h) does not
   print `mantle.window_used` with "clipped (cap): 64.7 h requested, 6.0 h
   used", or the sidecar does not record the window used (6 h from the
   later record start, UTC ISO) and `window_clipped` {64.7, 6.0, "cap"};
   `--engine aurora --mantle-window clip` is not refused naming
   --mantle-window; or `crust.engine_mantle.check_window`'s refusal (when
   MANTLE is installed) no longer reads "the window is 42.0 h; ... at most
   24 h apart".
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import types
from pathlib import Path

import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.mantle_window import choose_window, clip_text, covered_spans  # noqa: E402

H = 3600.0
T0 = pd.Timestamp("2023-02-27T00:00:00", tz="UTC").timestamp()


def hours(*pairs) -> list[tuple[float, float]]:
    """Build spans from (start, end) pairs in hours after T0."""
    return [(T0 + a * H, T0 + b * H) for a, b in pairs]


def near(a: float, b: float, tol: float = 1e-6) -> bool:
    """Compare two numbers to an absolute tolerance."""
    return abs(a - b) <= tol


def refused(fn, *args, **kwargs) -> str:
    """Call fn and return the text of the ValueError it must raise."""
    try:
        fn(*args, **kwargs)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"{fn.__name__}{args} was not refused")


def test_covered_spans() -> None:
    fs = 1000.0
    n = int(H * fs)
    joined = covered_spans([(T0 + H, n), (T0, n)], fs)
    assert joined == [(T0, T0 + 2 * H)], joined
    assert len(covered_spans([(T0, n), (T0 + H + 0.0004, n)], fs)) == 1
    apart = covered_spans([(T0, n), (T0 + H + 0.002, n)], fs)
    assert len(apart) == 2 and near(apart[0][1], T0 + H), apart
    print(f"  two 1 h runs back to back: {len(joined)} span of 2 h; 0.4 ms late joined, 2 ms late apart")


def test_within_cap_and_covered() -> None:
    c = choose_window(hours((0, 20)), hours((1, 30)), 24.0)
    assert c.clipped is None and near(c.start, T0 + H) and near(c.end, T0 + 20 * H), c
    print(f"  19 h overlap, cap 24 h: {c.hours:.1f} h, {clip_text(c.clipped)}")


def test_over_the_cap() -> None:
    c = choose_window(hours((0, 70)), hours((2, 80)), 48.0)
    assert near(c.start, T0 + 2 * H) and near(c.end, T0 + 50 * H), c
    assert c.clipped == {"requested_hours": 68.0, "used_hours": 48.0, "reason": "cap"}, c.clipped
    t = 1.7e9 + 0.1
    tight = choose_window([(t, t + 70 * H)], [(t, t + 70 * H)], 48.0)
    assert (tight.end - tight.start) / H <= 48.0, (tight.end - tight.start) / H - 48.0
    print(f"  68 h overlap, cap 48 h: {clip_text(c.clipped)}, from the later start")


def test_gap() -> None:
    c = choose_window(hours((0, 10), (11.5, 30)), hours((0, 30)), 48.0)
    assert near(c.start, T0 + 11.5 * H) and near(c.end, T0 + 30 * H), c
    assert c.clipped == {"requested_hours": 30.0, "used_hours": 18.5, "reason": "gap"}, c.clipped
    print(f"  a 1.5 h gap at 10 h of 30 h: {clip_text(c.clipped)} from 11.5 h")


def test_gap_and_cap() -> None:
    c = choose_window(hours((0, 10), (11.5, 70)), hours((0, 70)), 48.0)
    assert near(c.start, T0 + 11.5 * H) and near(c.end, T0 + 59.5 * H), c
    assert c.clipped == {"requested_hours": 70.0, "used_hours": 48.0, "reason": "cap and gap"}, c.clipped
    g = choose_window(hours((0, 30), (31, 50)), hours((0, 50)), 40.0)
    assert near(g.start, T0) and near(g.end, T0 + 30 * H), g
    assert g.clipped == {"requested_hours": 50.0, "used_hours": 30.0, "reason": "gap"}, g.clipped
    late = choose_window(hours((0, 50), (51, 70)), hours((0, 70)), 24.0)
    assert near(late.start, T0) and near(late.end, T0 + 24 * H), late
    assert late.clipped == {"requested_hours": 70.0, "used_hours": 24.0, "reason": "cap"}, late.clipped
    print(f"  gap at 10 h of 70 h, cap 48 h: {clip_text(c.clipped)}; gap at 30 h of 50 h, cap 40 h: "
          f"{clip_text(g.clipped)}; gap at 50 h of 70 h, cap 24 h: {clip_text(late.clipped)}")


def test_runs_differ_between_sites() -> None:
    c = choose_window(hours((0, 20), (21, 40)), hours((0, 15), (16, 40)), 48.0)
    assert near(c.start, T0 + 21 * H) and near(c.end, T0 + 40 * H), c
    assert c.clipped and c.clipped["reason"] == "gap" and near(c.clipped["used_hours"], 19.0), c.clipped
    print(f"  local gap 20-21 h, remote gap 15-16 h: {c.hours:.1f} h from 21 h ({c.clipped['reason']})")


def test_no_common_hour_and_given_bounds() -> None:
    short = refused(choose_window, hours((0, 10)), hours((9.5, 20)), 48.0)
    assert "0.50 h" in short and "at least 1 h" in short, short
    none = refused(choose_window, hours((0, 10)), hours((11, 20)), 48.0)
    assert "no overlap" in none, none
    c = choose_window(hours((0, 70)), hours((0, 70)), 48.0, start=T0 + 10 * H, end=T0 + 20 * H)
    assert c.clipped is None and near(c.start, T0 + 10 * H) and near(c.end, T0 + 20 * H), c
    print(f"  0.5 h in common: {short!r}; disjoint: {none!r}; 10-20 h given: kept")


def _survey(root: Path) -> Path:
    """Write a two-site survey (A 0-64.7 h, B 0-70 h after T0) without masks; return its survey.yaml."""
    iso = lambda h: pd.Timestamp(T0 + h * H, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    sites = {"A": {"latitude": 31.0, "longitude": -5.5, "start": iso(0), "end": iso(64.7)},
             "B": {"latitude": 31.05, "longitude": -5.5, "start": iso(0), "end": iso(70)}}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text("{}\n", encoding="utf-8")
    return root / "survey.yaml"


def _process_rr():
    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from loguru import logger

    logger.remove()
    return module


def _lines(pr, res) -> list[str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        pr.print_resolution(res)
    return buf.getvalue().splitlines()


def test_process_rr_refuse_unchanged_and_clip() -> None:
    import datetime as dt

    pr = _process_rr()
    survey_yaml = _survey(Path(tempfile.mkdtemp(prefix="mantle_window_unit_")))
    started = dt.datetime(2026, 9, 27, 12, 0).astimezone()
    base = [str(survey_yaml), "A", "B", "--engine", "mantle", "--no-masks", "--mantle-max-hours", "6"]
    plain = pr.build_parser().parse_args(base)
    explicit = pr.build_parser().parse_args(base + ["--mantle-window", "refuse"])
    res_plain, res_explicit = pr.resolve(plain, started), pr.resolve(explicit, started)
    lines = _lines(pr, res_plain)
    assert lines == _lines(pr, res_explicit), "an explicit --mantle-window refuse changed the resolution"
    assert not any(ln.startswith("mantle.window") for ln in lines), [ln for ln in lines if "mantle" in ln]
    assert lines[-2:] == ["mantle.whiten: none", "mantle.max_hours: 6"], lines[-3:]
    now = dt.datetime.now().astimezone()
    q = {"pmin": 0.1, "pmax": 10.0, "xy": 45.0, "yx": -135.0, "xy_ok": True, "yx_ok": True, "reason": ""}
    side = pr.build_sidecar(res_plain, plain, started, now, Path("x.edi"), Path("x.png"), q, [])
    assert side["window"] == {"start": None, "end": None} and "window_clipped" not in side, side["window"]

    try:
        pr.resolve(pr.build_parser().parse_args([str(survey_yaml), "A", "B", "--no-masks", "--mantle-window",
                                                 "clip"]), started)
    except SystemExit as exc:
        assert "--mantle-window" in str(exc) and "aurora" in str(exc), str(exc)
    else:
        raise AssertionError("aurora took --mantle-window clip")

    clip = pr.build_parser().parse_args(base + ["--mantle-window", "clip"])
    res = pr.resolve(clip, started)
    assert "mantle.window: clip" in _lines(pr, res)
    spans = {"a.h5": hours((0, 64.7)), "b.h5": hours((0, 70))}
    fake = types.ModuleType("crust.engine_mantle")
    fake.archive_spans = lambda path: spans[Path(path).name]
    import crust

    saved = (sys.modules.get("crust.engine_mantle"), getattr(crust, "engine_mantle", None))
    sys.modules["crust.engine_mantle"], crust.engine_mantle = fake, fake
    try:
        choice = pr.choose_mantle_window(res, Path("a.h5"), Path("b.h5"), None, None)
    finally:
        if saved[0] is None:
            sys.modules.pop("crust.engine_mantle", None)
        else:
            sys.modules["crust.engine_mantle"] = saved[0]
        if saved[1] is None:
            del crust.engine_mantle
        else:
            crust.engine_mantle = saved[1]
    line = pr.mantle_window_line(res)
    assert line.startswith("mantle.window_used: 2023-02-27 00:00:00 to 2023-02-27 06:00:00 UTC (6.00 h;"), line
    assert "clipped (cap): 64.7 h requested, 6.0 h used" in line, line
    side = pr.build_sidecar(res, clip, started, now, Path("x.edi"), Path("x.png"), q, [])
    assert side["window"] == {"start": "2023-02-27T00:00:00+00:00", "end": "2023-02-27T06:00:00+00:00"}, side["window"]
    assert side["window_clipped"] == {"requested_hours": 64.7, "used_hours": 6.0, "reason": "cap"}, side
    assert near(choice.hours, 6.0)
    print(f"  refuse (default and explicit): same lines, no mantle.window line, sidecar window {side['window']!r} "
          f"only under clip; aurora refused; {line}")

    try:
        from crust import engine_mantle
    except ImportError as exc:  # MANTLE is installed separately
        print(f"  (MANTLE not installed, check_window not checked: {exc})")
        return
    text = refused(engine_mantle.check_window, 42.0)
    assert text.startswith("the window is 42.0 h;") and "at most 24 h apart" in text, text
    print(f"  check_window unchanged: {text!r}")


def main() -> int:
    """Run every test; return 1 when any failed."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    tests = [test_covered_spans, test_within_cap_and_covered, test_over_the_cap, test_gap, test_gap_and_cap,
             test_runs_differ_between_sites, test_no_common_hour_and_given_bounds,
             test_process_rr_refuse_unchanged_and_clip]
    failed = 0
    for t in tests:
        print(t.__name__)
        try:
            t()
            print("  PASS")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
