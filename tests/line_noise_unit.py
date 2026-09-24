# -*- coding: utf-8 -*-
"""
Unit test for the step, shift, burst and coherence measures of scripts/line_noise_profile.py

Builds a synthetic archive in the mth5 layout (one station, one 500 Hz run
of a little over two hours whose start lies 1.3 ms past a whole second, so
no sample falls on a clock minute) and profiles it with the script's own
`profile_site`, 20 minutes every half hour from the clock hour. The
background is coherent noise: hy and hx are two independent unit white
series, ex is hy plus as much independent noise (coherence 0.5) and ey is
hx plus half as much (coherence 0.8). On top of it ey carries one-sided
plateaus of 50 units (about 45 standard deviations of ey): four of 20 s in
the first window, four of 40 s in the second and two of 120 s in the
third, none nearer than 100 s to a window edge; hx carries a 2 s burst of
white noise at 100 times its own level at 30 s past every minute around
the first window. The fourth window has nothing planted. The output tag of
`select_sites` and the `r_shift_ey` column of `pair_table` are checked on
small fixtures.

Usage:
    python tests/line_noise_unit.py

    Writes nothing outside a temporary directory; prints the criteria, one
    line per check and PASS, or FAIL with exit status 1.

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** `shift_ey` differs by more than 0.005 from the
planted fraction of plateau samples in any of the first three windows
(80/1200 = 0.0667 for the 20 s plateaus, 160/1200 = 0.1333 for the 40 s
ones, 240/1200 = 0.2 for the 120 s ones) or exceeds 0.002 in the fourth;
`step_ey` differs by more than 0.005 from 0.0667 in the first window or
exceeds 0.002 in the fourth; `step_ex` or `shift_ex` exceeds 0.002 in any
window (nothing is planted in ex); `burst_hx` differs by more than 0.002
from the planted 40/1200 = 0.0333 in the first window (the burst samples
that stay under the threshold and the band-pass ringing past each burst
edge move it in opposite directions, each by less than that) or exceeds
0.001 in the others, or `burst_hy` exceeds 0.001 in any window; the fourth
window's ex-hy or ey-hx coherence is more than 0.02 from 0.5 or 0.8 in
either band; a window's `hour_start_utc` is not its clock half hour to the
second, it has other than four whole 5-minute envelope cells beginning at
its start, or a cell of the first window is more than 0.01 from 20/300;
`select_sites` does not tag a single prefix with the prefix, an explicit
list with the names joined by "_" and no names with "all"; or `pair_table`
does not give `r_shift_ey` = +1 and `r_step_ey` = -1 (within 1e-9) for two
sites whose `shift_ey` are linearly related and whose `step_ey` are
opposite. The `step_ey` of the second and third windows is printed for
information only: the 60 s running median follows plateaus longer than
about 30 s, which is what `shift_ey` is for.
"""

from __future__ import annotations

import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import h5py
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import line_noise_profile as lnp  # noqa: E402

FS = 500.0
SCALE = 1000.0  # counts per unit of the synthetic series
T0 = pd.Timestamp("2023-07-19T10:54:00.0013+00:00")
DURATION_S = 7320.0
WINDOW_STARTS = ("11:00", "11:30", "12:00", "12:30")
PLATEAU = 50.0
BURST = 100.0
# plateaus of ey per window: (start in s from the window start, length in s)
PLATEAUS = {
    0: [(100.0, 20.0), (400.0, 20.0), (700.0, 20.0), (1000.0, 20.0)],
    1: [(100.0, 40.0), (400.0, 40.0), (700.0, 40.0), (1000.0, 40.0)],
    2: [(150.0, 120.0), (800.0, 120.0)],
    3: [],
}
PLANTED_BURST = 40.0 / 1200.0
TOL_FRAC = 0.005
TOL_ZERO = 0.002
TOL_BURST = 0.002
TOL_COH = 0.02


def _window_start(k: int) -> pd.Timestamp:
    """Nominal start of window `k`."""
    return pd.Timestamp(f"2023-07-19T{WINDOW_STARTS[k]}:00+00:00")


def _index(t: pd.Timestamp) -> int:
    """Index of the sample nearest to time `t`."""
    return int(round((t - T0).value * FS / 1e9))


def write_archive(path: Path, seed: int = 11) -> None:
    """Write the synthetic archive described in the module docstring.

    Args:
        path (Path): The HDF5 file to create.
        seed (int): Seed of the noise draw.
    """
    rng = np.random.default_rng(seed)
    n = int(round(DURATION_S * FS))
    hy = rng.standard_normal(n)
    hx = rng.standard_normal(n)
    ex = hy + rng.standard_normal(n)
    ey = hx + 0.5 * rng.standard_normal(n)
    for k, plateaus in PLATEAUS.items():
        for start, length in plateaus:
            a = _index(_window_start(k) + pd.Timedelta(seconds=start))
            ey[a : a + int(round(length * FS))] += PLATEAU
    for m in range(-2, 22):
        a = _index(_window_start(0) + pd.Timedelta(seconds=60 * m + 30))
        hx[a : a + int(round(2 * FS))] += BURST * rng.standard_normal(int(round(2 * FS)))
    with h5py.File(path, "w") as f:
        run = f.create_group("Experiment/Surveys/SV/Stations/SYN/sr500_0001")
        run.attrs["time_period.start"] = T0.isoformat()
        run.attrs["sample_rate"] = FS
        for c, v in (("ex", ex), ("ey", ey), ("hx", hx), ("hy", hy)):
            run.create_dataset(c, data=np.round(v * SCALE).astype("int32"))


@lru_cache(maxsize=1)
def profile() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Profile the synthetic archive once, 20 minutes every half hour."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "SYN.h5"
        write_archive(path)
        rows, env = lnp.profile_site(path, "SV", "SYN", [], 0.5, 20.0, "clock", ZoneInfo("UTC"))
    return pd.DataFrame(rows), pd.DataFrame(env)


def _planted(k: int) -> float:
    """Planted fraction of plateau samples in window `k`."""
    return sum(length for _, length in PLATEAUS[k]) / 1200.0


def check_plateaus() -> list[tuple[str, bool, str]]:
    """Step and shift fractions of ey and ex against the planted plateaus."""
    df, _ = profile()
    out = []
    for k in range(4):
        w = df.iloc[k]
        planted = _planted(k)
        if planted > 0:
            ok = abs(w.shift_ey - planted) <= TOL_FRAC
            out.append((f"window {k + 1} shift_ey = planted {planted:.4f} +- {TOL_FRAC}", ok, f"{w.shift_ey:.4f}"))
        else:
            out.append((f"window {k + 1} shift_ey <= {TOL_ZERO}", w.shift_ey <= TOL_ZERO, f"{w.shift_ey:.4f}"))
        if k == 0:
            ok = abs(w.step_ey - planted) <= TOL_FRAC
            out.append((f"window 1 step_ey = planted {planted:.4f} +- {TOL_FRAC}", ok, f"{w.step_ey:.4f}"))
        if k == 3:
            out.append((f"window 4 step_ey <= {TOL_ZERO}", w.step_ey <= TOL_ZERO, f"{w.step_ey:.4f}"))
        worst_ex = max(w.step_ex, w.shift_ex)
        out.append((f"window {k + 1} step_ex, shift_ex <= {TOL_ZERO}", worst_ex <= TOL_ZERO,
                    f"{w.step_ex:.4f}, {w.shift_ex:.4f}"))
    return out


def check_bursts_and_coherence() -> list[tuple[str, bool, str]]:
    """Burst fractions of the coils and the coherence of the quiet window."""
    df, _ = profile()
    out = []
    for k in range(4):
        w = df.iloc[k]
        if k == 0:
            ok = abs(w.burst_hx - PLANTED_BURST) <= TOL_BURST
            out.append((f"window 1 burst_hx = planted {PLANTED_BURST:.4f} +- {TOL_BURST}", ok, f"{w.burst_hx:.4f}"))
        else:
            out.append((f"window {k + 1} burst_hx <= 0.001", w.burst_hx <= 0.001, f"{w.burst_hx:.4f}"))
        out.append((f"window {k + 1} burst_hy <= 0.001", w.burst_hy <= 0.001, f"{w.burst_hy:.4f}"))
    w = df.iloc[3]
    for col, want in (("coh_exhy_lo", 0.5), ("coh_exhy_hi", 0.5), ("coh_eyhx_lo", 0.8), ("coh_eyhx_hi", 0.8)):
        out.append((f"window 4 {col} = {want} +- {TOL_COH}", abs(w[col] - want) <= TOL_COH, f"{w[col]:.4f}"))
    return out


def check_window_times() -> list[tuple[str, bool, str]]:
    """Window starts to the second and whole envelope cells from a start between samples."""
    df, env = profile()
    out = []
    got = list(df["hour_start_utc"])
    want = [_window_start(k).isoformat() for k in range(4)]
    out.append(("hour_start_utc on the clock half hours", got == want, ", ".join(g[11:] for g in got)))
    cells = pd.to_datetime(env["cell_start_utc"], format="ISO8601")
    for k in range(4):
        t = _window_start(k)
        mine = env[(cells >= t) & (cells < t + pd.Timedelta(minutes=20))]
        expect = [(t + pd.Timedelta(minutes=5 * i)).isoformat() for i in range(4)]
        ok = list(mine["cell_start_utc"]) == expect and len(env[(cells > t - pd.Timedelta(minutes=10))
                                                              & (cells < t)]) == 0
        out.append((f"window {k + 1}: four whole envelope cells from its start", ok,
                    ", ".join(c[11:16] for c in mine["cell_start_utc"])))
    first = env[(cells >= _window_start(0)) & (cells < _window_start(0) + pd.Timedelta(minutes=20))]["env_ey"]
    ok = len(first) == 4 and bool((first - 20.0 / 300.0).abs().max() <= 0.01)
    out.append(("window 1 envelope cells = 20/300 +- 0.01", ok, ", ".join(f"{v:.4f}" for v in first)))
    return out


def check_output_tag() -> list[tuple[str, bool, str]]:
    """Output tags of a prefix, an explicit list and no names."""
    out = []
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "mth5").mkdir()
        for s in ("X01", "X02", "Y10"):
            (Path(tmp) / "mth5" / f"{s}.h5").touch()
        survey = SimpleNamespace(workspace=Path(tmp))
        cases = (
            (["X"], (["X01", "X02"], "X")),
            (["X01", "Y10"], (["X01", "Y10"], "X01_Y10")),
            ([], (["X01", "X02", "Y10"], "all")),
        )
        for names, want in cases:
            got = lnp.select_sites(survey, names)
            out.append((f"select_sites({names}) -> {want}", got == want, str(got)))
    return out


def check_pair_columns() -> list[tuple[str, bool, str]]:
    """r_shift_ey and r_step_ey of two fixture sites."""
    hours = pd.date_range("2023-07-19T00:00:00+00:00", periods=8, freq="h")
    x = np.array([0.01, 0.05, 0.02, 0.2, 0.0, 0.08, 0.03, 0.11])
    base = dict(hour_start_utc=[h.isoformat() for h in hours], burst_hx=x[::-1])
    a = pd.DataFrame(dict(site="X01", step_ey=x, shift_ey=x, raw_crc=1, **base))
    b = pd.DataFrame(dict(site="X02", step_ey=-x, shift_ey=2.0 * x + 0.01, raw_crc=2, **base))
    env = pd.DataFrame(columns=["site", "cell_start_utc", "env_ey"])
    p = lnp.pair_table(pd.concat([a, b], ignore_index=True), env).iloc[0]
    ok = abs(p.r_shift_ey - 1.0) <= 1e-9 and abs(p.r_step_ey + 1.0) <= 1e-9
    return [("pair_table r_shift_ey = +1, r_step_ey = -1", ok, f"{p.r_shift_ey:+.6f}, {p.r_step_ey:+.6f}")]


def main() -> int:
    """Run every check, print one line each and return the exit status."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    checks = [check_plateaus, check_bursts_and_coherence, check_window_times, check_output_tag, check_pair_columns]
    results = [r for check in checks for r in check()]
    for name, ok, detail in results:
        print(f"  {'ok  ' if ok else 'FAIL'}  {name}: {detail}")
    df, _ = profile()
    print("\n  for information, step_ey (60 s median) against the planted fraction:")
    for k in range(3):
        print(f"    window {k + 1}: step_ey {df.iloc[k].step_ey:.4f}, shift_ey {df.iloc[k].shift_ey:.4f}, "
              f"planted {_planted(k):.4f}")
    failed = [name for name, ok, _ in results if not ok]
    if failed:
        print(f"\nFAIL  line_noise_unit ({len(failed)} of {len(results)} checks): {'; '.join(failed)}")
        return 1
    print(f"\nPASS  line_noise_unit ({len(results)} checks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
