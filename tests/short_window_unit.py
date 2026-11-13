# -*- coding: utf-8 -*-
"""
Unit test for the short-window guards of mt_workbench.process.process_station

Synthetic part (always runs): `band_windows` on an aurora-shaped
``decimation_dict`` whose npts are paired with a level's bands in reverse
order, as aurora 0.6.2 pairs them (the 10 min C18 rr C19 window's level 6:
npts 10, 20, 20, 25, 35, 40 on bands of 8, 7, 5, 4, 4, 2 harmonics);
`drop_short_bands` and `mt_workbench.products.drop_bad_errors` on a TF
built by hand; the default floor (`MIN_BAND_WINDOWS`, 2) on the same TF
with level 6 cut to 3 windows, and the periods removed as the TF's
`dropped_short_bands`; `drop_bad_errors` on the TF that scripts/process_rr.py's
`merge_rows` builds from two masked runs (rows ex from a run on 1, 2, 4
and 8 s, rows ey and hz from the base run on 1, 2, 8 and 16 s), written
as an EDI; `Survey.processing` and `Survey.min_band_windows` on a survey
whose `processing:` block holds the key.

Real part (skipped when the bench workspace is not mounted):
`process_station` on the filtered variants C18_fb647033d.h5 and
C19_f7b05dc48.h5 of `qc/survey/pipeline_bench_20261002/bench_ws/mth5`,
opened read-only, over the 10 min window 2023-09-23 00:00-00:10,
with the Morocco survey's band scheme and outputs ex,
ey. It runs three times: as shipped (the default floor, 2); with the floor 0; and with
the floor 0 and the error guard replaced by a no-op, the control that
gives aurora's own output.

Usage:
    python tests/short_window_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `band_windows` does not give 5 windows to every
band of the reversed level and 1 to every band of a level of 1 window;
`drop_short_bands` keeps a period below the floor or drops one at or above
it, or the TF's `dropped_short_bands` is not the sorted list it returned (an
empty list for a floor that drops nothing); `MIN_BAND_WINDOWS` or
`process_station`'s default floor is not 2, or the default floor drops the
3-window level (at the old 5 it does, so this trips); `drop_bad_errors` keeps a period with a zero or NaN Z error on every
row or drops a clean one, touches a Z row that is NaN at every period (not
estimated), or, where one row alone has a zero error, removes the period
or changes the other row, or does not make that row's residual-covariance
row and column NaN at that period, or changes any other residual-covariance
entry; on the merged TF it removes any of the 5
periods (the first guard removed 4 and 16 s from every row because one
row's run lacked each), changes any value a run estimated, or does not
leave ex EMPTY (1e32) at 16 s and ey and hz at 4 s in the EDI;
survey.yaml's `min_band_windows` reaches `Survey.processing` (the band
scheme's keywords) or `Survey.min_band_windows` does not read it; or, on
the bench archives, the 10 min TF as shipped holds a zero or non-finite Z
error or any period of level 7 (1 window), or holds a period other than
the control's minus level 7's, or its `dropped_short_bands` is not level 7's
six periods; with the floor 0 the 45.976 s period (zero
errors) is written; or the control does not reproduce case 3b's zero
errors at 45.976 s (then the guards are untested).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import yaml  # noqa: E402

BENCH = Path(r"D:\MT_DATA\MT_Morocco_Atlas_Mountains_Workspace\qc\survey\pipeline_bench_20261002\bench_ws\mth5")
SURVEY = REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "survey.yaml"
# the 10 min C18 rr C19 window's levels 6 and 7 as aurora recorded them: periods, npts, harmonics
LEVEL6 = [(3.62039, 10, (33, 40)), (4.5614, 20, (26, 32)), (5.74701, 20, (21, 25)), (7.24077, 25, (17, 20)),
          (9.1228, 35, (13, 16)), (11.494, 40, (11, 12))]
LEVEL7 = [(14.4815, 2, (33, 40)), (18.2456, 4, (26, 32)), (22.988, 4, (21, 25)), (28.9631, 5, (17, 20)),
          (36.4912, 7, (13, 16)), (45.976, 8, (11, 12))]


def _tf(periods, zero_at=None, nan_row=False):
    """Build a TF with Z on `periods`, its errors 0.1, and an aurora decimation_dict of LEVEL6 and LEVEL7."""
    from mt_metadata.transfer_functions.core import TF

    tf = TF()
    tf.station = "C18"
    tf.period = np.asarray(periods, dtype=float)
    z = np.zeros((len(periods), 2, 2), dtype=complex)
    z[:, 0, 1], z[:, 1, 0] = 1.0 + 1.0j, -1.0 - 1.0j
    z[:, 0, 0], z[:, 1, 1] = 0.1 + 0.1j, -0.1 - 0.1j
    err = np.full((len(periods), 2, 2), 0.1)
    if nan_row:  # an output row aurora was not asked for: NaN at every period
        z[:, 1, :], err[:, 1, :] = np.nan, np.nan
    if zero_at is not None:
        err[zero_at] = 0.0
    tf.impedance = z
    tf.impedance_error = err
    tf.decimation_dict = {f"{p:.10g}": {"level": level, "bands": bands, "npts": npts, "sample_rate": 1.0}
                          for level, rows in ((6, LEVEL6), (7, LEVEL7)) for p, npts, bands in rows}
    return tf


def test_band_windows_and_floor() -> None:
    """Check the window count per level under aurora's reversed pairing, and the floor."""
    from mt_workbench.process import band_windows, drop_short_bands

    periods = [p for p, _, _ in LEVEL6 + LEVEL7]
    tf = _tf(periods)
    got = band_windows(tf)
    assert {round(p, 4): got[p] for p in got} == {round(p, 4): (5 if p < 14 else 1) for p in periods}, got
    dropped = drop_short_bands(tf, 5, "C18 (test)")
    assert [round(p, 4) for p in dropped] == [round(p, 4) for p, _, _ in LEVEL7], dropped
    assert np.allclose(tf.period, [p for p, _, _ in LEVEL6]), tf.period
    assert tf.dropped_short_bands == dropped == sorted(dropped), tf.dropped_short_bands
    tf = _tf(periods)
    assert drop_short_bands(tf, 1, "C18 (test)") == [] and tf.period.size == 12, "a floor of 1 dropped a period"
    assert tf.dropped_short_bands == [], tf.dropped_short_bands
    assert drop_short_bands(tf, 0, "C18 (test)") == [], "a floor of 0 dropped a period"
    assert tf.dropped_short_bands == [], tf.dropped_short_bands
    print(f"  band_windows: level 6 -> {got[LEVEL6[0][0]]}, level 7 -> {got[LEVEL7[0][0]]} windows; "
          f"floor 5 dropped {len(dropped)} periods ({dropped[0]:.4g}-{dropped[-1]:.4g} s), floors 1 and 0 none")


def test_default_floor() -> None:
    """Check the default floor of 2: a level of 3 windows is kept, a level of 1 window dropped."""
    import inspect

    from mt_workbench.process import MIN_BAND_WINDOWS, band_windows, drop_short_bands, process_station

    default = inspect.signature(process_station).parameters["min_band_windows"].default
    assert MIN_BAND_WINDOWS == 2 and default == 2, (MIN_BAND_WINDOWS, default)
    periods = [p for p, _, _ in LEVEL6 + LEVEL7]
    tf = _tf(periods)
    # level 6 cut to 3 windows: npts scaled by 3/5 on the same bands (30 harmonics, 90 npts)
    for p, npts, _ in LEVEL6:
        tf.decimation_dict[f"{p:.10g}"]["npts"] = npts * 3 // 5
    counts = band_windows(tf)
    assert {counts[p] for p, _, _ in LEVEL6} == {3} and {counts[p] for p, _, _ in LEVEL7} == {1}, counts
    dropped = drop_short_bands(tf, MIN_BAND_WINDOWS, "C18 (test)")
    assert [round(p, 4) for p in dropped] == [round(p, 4) for p, _, _ in LEVEL7], dropped
    assert np.allclose(tf.period, [p for p, _, _ in LEVEL6]), tf.period
    assert tf.dropped_short_bands == dropped, tf.dropped_short_bands
    print(f"  default floor {MIN_BAND_WINDOWS}: the 3-window level kept (6 periods), the 1-window level dropped "
          f"({len(dropped)} periods, {dropped[0]:.4g}-{dropped[-1]:.4g} s), recorded on the TF")


def test_bad_errors_dropped() -> None:
    """Check the zero-error guard on a hand-built TF, with a NaN output row left alone."""
    from mt_workbench.products import bad_error_periods, drop_bad_errors

    periods = [p for p, _, _ in LEVEL6]
    tf = _tf(periods, zero_at=2, nan_row=True)
    assert bad_error_periods(tf).tolist() == [False, False, True, False, False, False], bad_error_periods(tf)
    dropped = drop_bad_errors(tf, "C18 (test)")
    assert [round(p, 4) for p in dropped] == [5.747], dropped
    assert tf.period.size == 5 and not bad_error_periods(tf).any()
    clean = _tf(periods, nan_row=True)
    assert drop_bad_errors(clean, "C18 (test)") == [] and clean.period.size == 6, "a clean TF lost a period"
    nan_err = _tf(periods)
    nan_err.impedance_error = np.where(np.arange(6)[:, None, None] == 4, np.nan, 0.1) * np.ones((6, 2, 2))
    assert [round(p, 4) for p in drop_bad_errors(nan_err, "C18 (test)")] == [9.1228]
    one_row = _tf(periods)
    err = np.full((6, 2, 2), 0.1)
    err[3, 0, :] = 0.0  # ex's errors at 7.24 s
    one_row.impedance_error = err
    rc = one_row._transfer_function["residual_covariance"]
    rc.values[:] = (np.arange(rc.size).reshape(rc.shape) + 1.0) * (1.0 + 0.5j)  # every entry finite and distinct
    ex_out, ex_in = list(rc.coords["output"].values).index("ex"), list(rc.coords["input"].values).index("ex")
    want = rc.values.copy()
    want[3, ex_out, :], want[3, :, ex_in] = np.nan, np.nan
    assert drop_bad_errors(one_row, "C18 (test)") == [] and one_row.period.size == 6, "a one-row zero error removed the period"
    z = np.asarray(one_row.impedance.data)
    assert np.isnan(z[3, 0]).all() and np.isfinite(np.delete(z[:, 0], 3, axis=0)).all(), z[:, 0]
    assert np.array_equal(z[:, 1], _tf(periods).impedance.data[:, 1]), "the clean row changed"
    got = np.asarray(one_row._transfer_function["residual_covariance"].values)
    assert np.isnan(got[3, ex_out, :]).all() and np.isnan(got[3, :, ex_in]).all(), \
        f"ex's residual-covariance row and column at 7.24 s not blanked: {got[3]}"
    assert np.array_equal(got, want, equal_nan=True), \
        f"a residual-covariance entry outside ex's row and column at 7.24 s changed: {np.argwhere(~((got == want) | (np.isnan(got) & np.isnan(want))))}"
    print("  drop_bad_errors: the zero-error period dropped, a NaN error dropped, a NaN output row left alone, "
          "a one-row zero error blanks that row alone, with its residual-covariance row and column "
          f"({int(np.isnan(got).sum())} of {got.size} entries NaN, the rest unchanged)")


def _load_process_rr():
    import importlib.util

    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _coded_tf(periods, offset: float):
    """Build a TF on `periods` whose every value encodes (offset, period index, output, input)."""
    from mt_metadata.transfer_functions.core import TF

    tf = TF()
    tf.station = "C18"
    tf.period = np.asarray(periods, dtype=float)
    ds = tf._transfer_function
    n, no, ni = ds["transfer_function"].shape
    code = (offset + 100.0 * np.arange(n)[:, None, None] + 10.0 * np.arange(no)[None, :, None]
            + np.arange(ni)[None, None, :])
    ds["transfer_function"].values[:] = code + 1j * code
    ds["transfer_function_error"].values[:] = code + 0.5
    ds["residual_covariance"].values[:] = code + 0.25j
    ds["inverse_signal_power"].values[:] = code - 0.5j
    return tf


def _edi_block(text: str, name: str) -> list[float]:
    """Read the values of one EDI data block (e.g. ZXYR) from the file's text."""
    lines = text.splitlines()
    k = next(i for i, ln in enumerate(lines) if ln.startswith(f">{name} "))
    values = []
    for ln in lines[k + 1:]:
        if ln.startswith(">"):
            break
        values += [float(v) for v in ln.split()]
    return values


def test_merged_rows_keep_their_periods() -> None:
    """Check the guard after process_rr.py's merge_rows: each row keeps every period its own run kept."""
    from mt_workbench.products import drop_bad_errors, write_edi
    from _scratch import scratch_dir

    pr = _load_process_rr()
    p1, p2 = [1.0, 2.0, 4.0, 8.0], [1.0, 2.0, 8.0, 16.0]
    tf1, tf2 = _coded_tf(p1, 1000.0), _coded_tf(p2, 5000.0)
    runs = [{"channels": ["ex"], "masks": [], "base": False}, {"channels": ["ey", "hz"], "masks": [], "base": True}]
    merged = pr.merge_rows([tf1, tf2], runs)
    dropped = drop_bad_errors(merged, "C18 (rows merged, test)")
    periods = np.asarray(merged.period, dtype=float).tolist()
    assert dropped == [] and periods == [1.0, 2.0, 4.0, 8.0, 16.0], f"removed {dropped}, kept {periods}"
    ds = merged._transfer_function
    for row, src, own in (("ex", tf1, p1), ("ey", tf2, p2), ("hz", tf2, p2)):
        for var in ("transfer_function", "transfer_function_error"):
            for p in periods:
                got = ds[var].sel(period=p, output=row, input=["hx", "hy"]).values
                if p in own:
                    want = src._transfer_function[var].sel(period=p, output=row, input=["hx", "hy"]).values
                    assert np.array_equal(got, want), f"{var} {row} at {p} s changed: {got} != {want}"
                else:
                    assert np.isnan(got).all(), f"{var} {row} at {p} s is not NaN: {got}"
    edi = scratch_dir("short_window_unit") / "merged_rows.edi"
    edi.parent.mkdir(parents=True, exist_ok=True)
    write_edi(merged, edi)
    text = edi.read_text(encoding="utf-8")
    empty = lambda vals: [k for k, v in enumerate(vals) if v >= 1e31]  # noqa: E731
    assert empty(_edi_block(text, "ZXYR")) == [4], _edi_block(text, "ZXYR")
    assert empty(_edi_block(text, "ZYXR")) == [2], _edi_block(text, "ZYXR")
    assert empty(_edi_block(text, "TXR.EXP")) == [2], _edi_block(text, "TXR.EXP")
    print(f"  merged rows: {len(periods)} periods kept ({periods}); ex EMPTY at 16 s, ey and hz at 4 s, every "
          f"value a run estimated unchanged; EDI {edi}")


def test_survey_key() -> None:
    """Check survey.yaml's processing: min_band_windows stays out of the band-scheme keywords."""
    from mt_workbench.survey import Survey

    cfg = {"name": "t", "data_root": ".", "processing": {"min_period": 0.005, "min_band_windows": 8}}
    survey = Survey(cfg, Path("."))
    assert survey.processing == {"min_period": 0.005}, survey.processing
    assert survey.min_band_windows == 8
    assert Survey({"name": "t", "data_root": "."}, Path(".")).min_band_windows is None
    print("  survey.yaml min_band_windows: 8 read, kept out of the band-scheme keywords; unset -> None")


def test_bench_ten_minutes() -> None:
    """Check the 10 min C18 rr C19 window on the bench archives (read-only): no zero error, level 7 dropped."""
    local, remote = BENCH / "C18_fb647033d.h5", BENCH / "C19_f7b05dc48.h5"
    if not (local.exists() and remote.exists() and SURVEY.exists()):
        print(f"  skipped: {local} or {remote} not found")
        return
    import mt_workbench.process as proc
    from mt_workbench.bands import build_band_scheme
    from mt_workbench.survey import Survey

    survey = Survey(yaml.safe_load(SURVEY.read_text(encoding="utf-8")), SURVEY.parent)
    scheme = build_band_scheme(1000.0, **survey.processing)
    before = {p: p.stat().st_mtime_ns for p in (local, remote)}

    recorded = []

    def run(**kwargs):
        tf = proc.process_station(local, "C18", remote, "C19", band_scheme=scheme, start="2023-09-23 00:00",
                                  end="2023-09-23 00:10", output_channels=["ex", "ey"], **kwargs)
        recorded.append(list(getattr(tf, "dropped_short_bands", ["absent"])))
        err = np.asarray(tf.impedance_error.data, dtype=float)
        zero = sorted({round(float(p), 3) for p, e in zip(tf.period, err) if not np.all(np.isfinite(e) & (e > 0))})
        return np.asarray(tf.period, dtype=float), zero

    shipped, zero_shipped = run()
    print(f"  bench 10 min as shipped: {shipped.size} periods, longest {shipped.max():.4g} s, zero/non-finite Z "
          f"errors at {zero_shipped} s")
    assert not zero_shipped, f"zero errors written at {zero_shipped}"
    floor0, zero_floor0 = run(min_band_windows=0)
    guard = proc.drop_bad_errors
    proc.drop_bad_errors = lambda tf, label: []
    try:
        control, zero_control = run(min_band_windows=0)
    finally:
        proc.drop_bad_errors = guard
    after = {p: p.stat().st_mtime_ns for p in (local, remote)}
    level7 = [p for p, _, _ in LEVEL7]
    print(f"  bench 10 min: control (aurora's own) {control.size} periods, zero/non-finite Z errors at {zero_control} s;"
          f" floor 0 {floor0.size} periods, zero errors at {zero_floor0}")
    assert after == before, "a bench archive changed"
    assert zero_control == [45.976], f"control: case 3b's zero errors not reproduced ({zero_control})"
    assert not zero_floor0 and not np.any(np.isclose(floor0, 45.976, rtol=1e-4)), "floor 0 wrote the zero-error period"
    assert not any(np.isclose(shipped, p, rtol=1e-4).any() for p in level7), "a level 7 (1 window) period was written"
    want = [p for p in control if not any(np.isclose(p, q, rtol=1e-4) for q in level7)]
    assert np.allclose(shipped, want), (shipped, want)
    assert len(recorded[0]) == len(level7) and np.allclose(recorded[0], sorted(level7), rtol=1e-4), recorded[0]
    print(f"  bench 10 min as shipped: dropped_short_bands {[round(p, 4) for p in recorded[0]]} (level 7)")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="WARNING", filter=lambda r: not r["name"].startswith("aurora"))
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ok  {test.__name__}")
        except (AssertionError, AttributeError, ImportError, TypeError) as exc:
            failed += 1
            print(f"  FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  short_window_unit ({len(tests) - failed} of {len(tests)} tests passed)")
    sys.exit(1 if failed else 0)
