"""Unit test for `mtproc.virtual` -- the stacked remote, unweighted and coherence-weighted.

    python tests/virtual_unit.py

Synthetic members, 1000 Hz, four 10-minute chunks plus a 1234-sample tail,
int32 counts like a B423 read, each member with its own DC offset (1e7-5e7
counts) and gain (0.9-1.1). The common field is white noise of 1000 counts
rms per coil; each clean coil adds 200 counts rms of its own noise.

- A1, A2, A3: clean on both coils;
- D: hx dead (the offset plus 1 count rms, no field), hy clean;
- C: clean, plus in chunk 2 only, on both coils, a mains-type burst: 5000
  counts rms broadband noise and a 10000-count 50 Hz tone.

Three clean members, not one: leave-one-out cannot say which of two live
coils is the bad one (each is the other's reference and coherence is
symmetric), so the test needs at least three live coils besides the noisy one.

Each member is written as a real MTH5 archive, laid out as
`mtproc.ingest.ingest_site` writes one (survey, station, run sr1000_0001
through RunTS / `from_runts`, int32 hx/hy) at `<workspace>/mth5/<member>.h5`
in a temporary workspace, so the archive reader and the chunk streaming are
under test; `build_synthetic_remote` runs end to end on them (a namespace
survey; the stack written to a temporary folder and read back with mth5).
**This test fails if**

1. the default build (no `weighting` argument) or ``weighting="none"`` writes
   hx/hy whose float32 bytes differ from the pre-weighting arithmetic, frozen
   here verbatim (float64 sum in member order, divided by the count, cast to
   float32), or its station comment differs from the pre-weighting string;
   and, as the control that this comparison can fail, if the weighted build's
   bytes are *equal* to it;
2. the weighted build gives D's dead hx a non-zero weight in any chunk, or
   D's live hy a zero weight in any chunk;
3. C's weight in the burst chunk is not below half its median weight over the
   other chunks, on either coil;
4. outside the burst chunk any live member's weight is off the equal share by
   more than 25 % (1/4 on hx, D dropped; 1/5 on hy);
5. with four identical members the weighted stack differs from the unweighted
   mean minus its median by more than 1e-9 of the signal rms (float64, before
   the archive's float32 cast), or any weight differs from 1/4 by more than 1e-6;
6. the weighted archive's run comment lacks the rule (weighting=coherence,
   600 s chunk, 0.1-10 s, 0.05) or a member's mean weight printed there
   differs from the returned weights by more than 0.0005, or a channel
   comment's per-mille weights differ from rint(1000 * weights);
7. `coherence_weights` does not turn gamma2 [0.9, 0.9, 0.04] into [0.5, 0.5, 0],
   a NaN into weight 0, or 30 equal members into 1/30 each (every one under
   the 0.05 floor: kept, not all dropped);
8. a 50 Hz-only burst (20000 counts, no broadband part) moves C's weight in
   its chunk by more than 10 % of C's median weight elsewhere. This is the
   rule's blind spot by design, asserted so it is known: the weight band is
   0.1-10 s, so a pure mains line never lowers a member's weight;
9. a member with no archive does not raise a ValueError that names it and
   says to build it first ("Build MTH5 on the Time Series tab, or
   scripts/ingest_site.py");
10. a member whose run starts half a sample (0.5 ms) after the others' does
    not raise the "sample grid does not align ... GPS timing assumption
    violated" ValueError;
11. with a member P archived as two runs -- the first 500 s, then a gap,
    then from 700 s to 300 s before the others' end -- the stack of A1, A2
    and P does not start 700 s after the others, is not N - 1 000 000
    samples long, or its hx/hy bytes differ from the numpy mean of the three
    aligned slices (P's second run is the larger overlap, so it must be the
    one taken); or the window [900 s, 1500.0002 s) does not give 600 001
    samples from 900 s with the same mean's bytes;
12. the streamed coherence-weighted hx/hy (float32 bytes in the archive)
    differ from a single-shot numpy computation on the whole arrays: in
    member order, the sum of each chunk's returned weight spread over its
    samples (the tail taking the last chunk's) times the member minus the
    median of its even subsample, cast to float32. (The unweighted single-shot
    reference is check 1's frozen mean.)
"""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import xarray as xr
from loguru import logger
from mth5.mth5 import MTH5
from mth5.timeseries import ChannelTS, RunTS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import mtproc.virtual as virtual  # noqa: E402

FS = 1000.0
CHUNK = int(virtual.WEIGHT_CHUNK_S * FS)
N_CHUNKS = 4
N = N_CHUNKS * CHUNK + 1234
BURST = 2  # the chunk C's burst sits in
FIELD_RMS = 1000.0
NOISE_RMS = 200.0
MEMBERS = ["A1", "A2", "A3", "C", "D"]
T0 = pd.Timestamp("2023-09-19T20:00:00")
SURVEY = "SYNTH"

failures: list[str] = []


def check(ok: bool, msg: str) -> None:
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)


def dataset(hx: np.ndarray, hy: np.ndarray) -> xr.Dataset:
    t = T0.to_datetime64() + np.arange(N) * np.timedelta64(1, "ms")
    return xr.Dataset(
        {"hx": ("time", np.rint(hx).astype("int32")), "hy": ("time", np.rint(hy).astype("int32"))},
        coords={"time": t},
    )


def synthetic_members(burst: str = "mains", seed: int = 11) -> dict[str, xr.Dataset]:
    """burst: "mains" (broadband + 50 Hz) or "tone" (50 Hz only)."""
    rng = np.random.default_rng(seed)
    field = {c: FIELD_RMS * rng.standard_normal(N) for c in ("hx", "hy")}
    t = np.arange(N) / FS
    out = {}
    for k, m in enumerate(MEMBERS):
        gain = 0.9 + 0.05 * k
        offset = 1e7 * (k + 1)
        coils = {c: offset + gain * field[c] + NOISE_RMS * rng.standard_normal(N) for c in ("hx", "hy")}
        if m == "D":
            coils["hx"] = offset + rng.standard_normal(N)
        if m == "C":
            sl = slice(BURST * CHUNK, (BURST + 1) * CHUNK)
            for c in coils:
                tone = 10000.0 if burst == "mains" else 20000.0
                coils[c][sl] += tone * np.sin(2 * np.pi * 50.0 * t[sl] + 0.3)
                if burst == "mains":
                    coils[c][sl] += 5000.0 * rng.standard_normal(sl.stop - sl.start)
        out[m] = dataset(coils["hx"], coils["hy"])
    return out


def write_archive(workspace: Path, site: str, runs: list[tuple[pd.Timestamp, dict]]) -> Path:
    """One member's archive as `ingest_site` lays it out: [(run start, {coil: int32 counts})]."""
    path = workspace / "mth5" / f"{site}.h5"
    path.parent.mkdir(parents=True, exist_ok=True)
    m = MTH5(file_version="0.2.0")
    m.open_mth5(path, mode="w")
    try:
        m.add_survey(SURVEY)
        station = m.add_station(site, survey=SURVEY)
        for i, (start, coils) in enumerate(runs, 1):
            run_id = f"sr{int(FS)}_{i:04d}"
            chans = [
                ChannelTS(channel_type="magnetic", data=np.asarray(data),
                          channel_metadata={"magnetic": {"component": c, "sample_rate": FS,
                                                         "time_period.start": start.isoformat()}})
                for c, data in coils.items()
            ]
            run = RunTS(chans, run_metadata={"id": run_id, "sample_rate": FS}, station_metadata={"id": site})
            station.add_run(run_id).from_runts(run)
    finally:
        m.close_mth5()
    return path


def write_members(datasets: dict, workspace: Path) -> Path:
    """Every synthetic member as a one-run archive starting at T0; returns the workspace."""
    for m, ds in datasets.items():
        write_archive(workspace, m, [(T0, {c: ds[c].data for c in ("hx", "hy")})])
    return workspace


def fake_survey(workspace: Path):
    return SimpleNamespace(
        name=SURVEY,
        sample_rate=FS,
        workspace=workspace,
        site=lambda m: SimpleNamespace(latitude=-31.0, longitude=139.0, filters=None),
    )


def build(workspace: Path, tmp: Path, name: str, members=None, start="2023-09-19", end="2023-09-20",
          **kwargs):
    """Run build_synthetic_remote on the archived members in `workspace`; return (path, weights_out)."""
    weights: dict = {}
    path = virtual.build_synthetic_remote(
        fake_survey(workspace), members or MEMBERS, start, end, name=name,
        out_path=tmp / f"{name}.h5", weights_out=weights, **kwargs,
    )
    return path, weights


def read_back(path: Path, name: str) -> dict:
    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(name, survey=SURVEY)
        run = st.get_run("sr1000_0001")
        out = {"station_comment": _text(st.metadata.comments), "run_comment": _text(run.metadata.comments)}
        for c in ("hx", "hy"):
            ch = m.get_channel(name, "sr1000_0001", c, SURVEY)
            out[c] = ch.hdf5_dataset[:]
            out[c + "_comment"] = _text(ch.metadata.comments)
            out[c + "_start"] = pd.Timestamp(str(ch.metadata.time_period.start))
    finally:
        m.close_mth5()
    return out


def _text(comment) -> str:
    value = getattr(comment, "value", comment)
    return "" if value is None else str(value)


def frozen_mean(datasets: dict, members: list[str], comp: str) -> np.ndarray:
    """The pre-weighting stack arithmetic, verbatim: float64 sum in member order / count -> float32."""
    acc = np.zeros(N, dtype="float64")
    for m in members:
        acc += datasets[m][comp].data.astype("float64")
    return (acc / len(members)).astype("float32")


def single_shot_weighted(datasets: dict, info: dict, comp: str) -> np.ndarray:
    """Check 12's reference: the whole-array weighted sum in plain numpy, cast to float32."""
    w = info["weights"]
    k = np.minimum(np.arange(N) // CHUNK, w.shape[1] - 1)  # the tail takes the last chunk's
    acc = np.zeros(N, dtype="float64")
    for i, m in enumerate(info["members"]):
        a = datasets[m][comp].data
        off = float(np.median(a[:: max(1, a.size // 1_000_000)]))
        acc += w[i][k] * (a.astype("float64") - off)
    return acc.astype("float32")


def raises(fn) -> str:
    """The ValueError message `fn()` raises, or "" if it raises none."""
    try:
        fn()
    except ValueError as exc:
        return str(exc)
    return ""


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    datasets = synthetic_members("mains")
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        ws = write_members(datasets, tmp / "ws_mains")

        # 1. the default is byte-identical to the pre-weighting arithmetic
        p_def, w_def = build(ws, tmp, "STK_default")
        p_none, _ = build(ws, tmp, "STK_none", weighting="none")
        p_coh, weights = build(ws, tmp, "STK_coh", weighting="coherence")
        default, none, coh = read_back(p_def, "STK_default"), read_back(p_none, "STK_none"), read_back(p_coh, "STK_coh")
        for c in ("hx", "hy"):
            ref = frozen_mean(datasets, MEMBERS, c)
            check(default[c].dtype == np.float32 and default[c].tobytes() == ref.tobytes(),
                  f"1. default build {c}: float32 bytes identical to the frozen mean")
            check(none[c].tobytes() == ref.tobytes(), f"1. weighting='none' {c}: bytes identical to the frozen mean")
            check(coh[c].tobytes() != ref.tobytes(), f"1. control: the weighted {c} is NOT byte-identical to the mean")
        want = (f"synthetic remote: mean of raw hx/hy counts from {', '.join(sorted(MEMBERS))}; "
                f"uncalibrated by design (RR estimator is calibration-invariant)")
        check(default["station_comment"] == want, "1. default station comment unchanged")
        check(not w_def and default["run_comment"] in ("", "None"), "1. default: no weights, no run comment")

        # 2-4. the weights
        hx, hy = weights["hx"], weights["hy"]
        wx, wy = hx["weights"], hy["weights"]
        i_d, i_c = hx["members"].index("D"), hx["members"].index("C")
        print(f"   hx weights by chunk:\n{np.round(wx, 3)}\n   hy weights by chunk:\n{np.round(wy, 3)}")
        print(f"   hx gamma2 (0.1-10 s):\n{np.round(hx['gamma2'], 3)}")
        check(np.all(wx[i_d] == 0.0), "2. D's dead hx has weight 0 in every chunk")
        check(np.all(wy[i_d] > 0.0), "2. D's live hy has a non-zero weight in every chunk")
        others = [k for k in range(N_CHUNKS) if k != BURST]
        for c, w in (("hx", wx), ("hy", wy)):
            ratio = w[i_c, BURST] / np.median(w[i_c, others])
            check(ratio < 0.5, f"3. {c}: C's burst-chunk weight is {ratio:.2f} of its usual (< 0.5)")
        live_x = [k for k, m in enumerate(hx["members"]) if m != "D"]
        dev_x = np.abs(wx[np.ix_(live_x, others)] - 0.25).max() / 0.25
        dev_y = np.abs(wy[:, others] - 0.2).max() / 0.2
        check(dev_x <= 0.25, f"4. hx outside the burst: live weights within {dev_x:.1%} of 1/4 (<= 25 %)")
        check(dev_y <= 0.25, f"4. hy outside the burst: weights within {dev_y:.1%} of 1/5 (<= 25 %)")
        check(np.allclose(wx.sum(axis=0), 1.0) and np.allclose(wy.sum(axis=0), 1.0),
              "   every chunk's weights sum to one")

        # 6. the provenance in the archive
        rc = coh["run_comment"]
        rule_ok = all(s in rc for s in ("weighting=coherence", "600 s chunk", "0.1-10 s", "under 0.05"))
        check(rule_ok, "6. run comment states the rule")
        worst = 0.0
        for c, info in weights.items():
            block = rc.split(f"{c}: ", 1)[1]
            for i, m in enumerate(info["members"]):
                got = float(re.search(rf"\b{m} ([0-9.]+) \(", block).group(1))
                worst = max(worst, abs(got - info["weights"][i].mean()))
        # printed to 3 decimals: rounding alone is up to 0.0005
        check(worst <= 0.0005 + 1e-9, f"6. run comment's mean weights match (worst {worst:.5f}, <= 0.0005)")
        per_mille_ok = True
        for c, info in weights.items():
            rows = coh[c + "_comment"].split(": ", 1)[1].split("; ")
            for i, row in enumerate(rows):
                m, *vals = row.split()
                per_mille_ok &= m == info["members"][i]
                per_mille_ok &= np.array_equal(np.array(vals, dtype=int), np.rint(info["weights"][i] * 1000).astype(int))
        check(per_mille_ok, "6. channel comments hold the per-chunk weights (per mille)")

        # 12. the streamed weighted stack == the single-shot numpy computation, bit for bit
        for c in ("hx", "hy"):
            ref = single_shot_weighted(datasets, weights[c], c)
            check(coh[c].tobytes() == ref.tobytes(),
                  f"12. weighted {c}: streamed bytes identical to the single-shot numpy sum")

        # 5. identical members: the weighted stack is the unweighted mean minus its median
        same = {m: datasets["A1"] for m in ("A1", "A2", "A3", "A4")}
        arrays = {m: same[m]["hx"].data for m in same}
        stacked, info = virtual._coherence_stack(arrays, FS)
        mean = frozen_mean(same, list(same), "hx").astype("float64")  # only for its median
        plain = datasets["A1"]["hx"].data.astype("float64")
        expect = plain - virtual._median(plain)
        err = np.abs(stacked - expect).max() / np.std(expect)
        check(err <= 1e-9, f"5. identical members: weighted == mean - median to {err:.1e} of the rms (<= 1e-9)")
        check(np.abs(info["weights"] - 0.25).max() <= 1e-6, "5. identical members: every weight is 1/4")
        check(np.abs(mean - plain).max() == 0.0, "   (identical members: the frozen mean is the member itself)")

        # 8. a 50 Hz-only burst is invisible to a 0.1-10 s weight (the blind spot, asserted)
        tone = synthetic_members("tone")
        _, w_tone = build(write_members(tone, tmp / "ws_tone"), tmp, "STK_tone", weighting="coherence")
        for c in ("hx", "hy"):
            w = w_tone[c]["weights"]
            k = w_tone[c]["members"].index("C")
            shift = abs(w[k, BURST] - np.median(w[k, others])) / np.median(w[k, others])
            check(shift <= 0.10, f"8. {c}: a 50 Hz-only burst moves C's weight by {shift:.1%} (<= 10 %)")

        # 9. a member without an archive: a named error that says to build it
        msg = raises(lambda: build(ws, tmp, "STK_missing", members=["A1", "A2", "X9"]))
        check("X9" in msg and "build it first" in msg
              and "Build MTH5 on the Time Series tab, or scripts/ingest_site.py" in msg,
              f"9. a member with no archive raises the named error: {msg[:90]!r}...")

        # 10. a run starting half a sample off the grid
        ws_half = tmp / "ws_half"
        for m in ("A1", "A2"):
            write_archive(ws_half, m, [(T0, {c: datasets[m][c].data for c in ("hx", "hy")})])
        write_archive(ws_half, "H", [(T0 + pd.Timedelta(microseconds=500),
                                      {c: datasets["A3"][c].data for c in ("hx", "hy")})])
        msg = raises(lambda: build(ws_half, tmp, "STK_half", members=["A1", "A2", "H"]))
        check("sample grid does not align" in msg and "GPS timing assumption violated" in msg,
              f"10. half a sample off the grid raises the grid error: {msg[:110]!r}...")

        # 11. a member recorded as two runs, the second only partly over the span
        ws_part = tmp / "ws_part"
        for m in ("A1", "A2"):
            write_archive(ws_part, m, [(T0, {c: datasets[m][c].data for c in ("hx", "hy")})])
        a, b = 700 * 1000, N - 300 * 1000
        a3 = {c: datasets["A3"][c].data for c in ("hx", "hy")}
        write_archive(ws_part, "P", [(T0, {c: v[: 500 * 1000] for c, v in a3.items()}),
                                     (T0 + pd.Timedelta(seconds=700), {c: v[a:b] for c, v in a3.items()})])
        trio = {m: datasets[m] for m in ("A1", "A2")} | {"P": datasets["A3"]}

        def aligned_mean(c: str, lo: int, hi: int) -> np.ndarray:
            acc = np.zeros(hi - lo, dtype="float64")
            for m in ("A1", "A2", "P"):
                acc += trio[m][c].data[lo:hi].astype("float64")
            return (acc / 3).astype("float32")

        part = read_back(build(ws_part, tmp, "STK_part", members=["A1", "A2", "P"])[0], "STK_part")
        ok = all(part[c + "_start"] == pd.Timestamp(T0 + pd.Timedelta(seconds=700), tz="UTC")
                 and part[c].size == b - a and part[c].tobytes() == aligned_mean(c, a, b).tobytes()
                 for c in ("hx", "hy"))
        check(ok, f"11. partly overlapping member: span {part['hx_start']} + {part['hx'].size} samples "
                  f"(want +700 s, {b - a}), bytes = the aligned mean")
        win = read_back(build(ws_part, tmp, "STK_win", members=["A1", "A2", "P"],
                              start="2023-09-19 20:15:00", end="2023-09-19 20:25:00.0002")[0], "STK_win")
        ok = all(win[c + "_start"] == pd.Timestamp("2023-09-19 20:15:00", tz="UTC")
                 and win[c].size == 600_001 and win[c].tobytes() == aligned_mean(c, 900_000, 1_500_001).tobytes()
                 for c in ("hx", "hy"))
        check(ok, f"11. window [900 s, 1500.0002 s): {win['hx_start']} + {win['hx'].size} samples "
                  f"(want 20:15:00, 600001), bytes = the aligned mean")

    # 7. the weight rule on hand-made gamma2
    w = virtual.coherence_weights(np.array([[0.9], [0.9], [0.04]]))
    check(np.allclose(w[:, 0], [0.5, 0.5, 0.0]), f"7. [0.9, 0.9, 0.04] -> {np.round(w[:, 0], 3)}")
    w = virtual.coherence_weights(np.array([[0.8], [np.nan], [0.8]]))
    check(np.allclose(w[:, 0], [0.5, 0.0, 0.5]), f"7. NaN gamma2 -> weight 0: {np.round(w[:, 0], 3)}")
    w = virtual.coherence_weights(np.full((30, 2), 0.7))
    check(np.allclose(w, 1 / 30), "7. 30 equal members (each under 0.05) keep 1/30, not all dropped")

    print()
    if failures:
        print(f"{len(failures)} FAILED:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
