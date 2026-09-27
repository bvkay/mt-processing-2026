# -*- coding: utf-8 -*-
"""
Unit test for the channels of masks.yaml entries and the mask history

Checks the optional `channels` key of a mask (`crust.masks`: `normalise`,
`save_masks`, `load_masks`, `masks_for_row`, `remote_channel_split`), the
per-row runs scripts/process_rr.py builds from it (`resolve`, `row_runs`,
the sidecar and the resolution lines) and the row merge of their transfer
functions (`merge_rows`, on synthetic mt_metadata TF objects), the per-row
stack of `crust.crosspower.stack_impedance` and `masked_chunks` on a
hand-made window store, and the mask history (`retire_masks`,
`restore_masks`, `load_history`, the atomic file replacement, and
scripts/retire_masks.py), on synthetic surveys in temporary folders. Runs
without an archive and without aurora.

Usage:
    python tests/mask_channels_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. `normalise` does not give channels "all" to an entry without the key, a
   sorted lower-case list to ["EY", "ex"], or accepts ["ez"], [] or the
   bare string "ex"; a site saved with an [ex] entry and an entry without
   the key does not write "channels: [ex]" on the first and no channels
   line on the second, or does not load them back as ["ex"] and "all"; the
   block of an entry without channels is not byte for byte BLOCK_X (the
   text the code wrote before the key existed); re-saving that site with
   the same list changes a byte of the file; or saving another site
   changes a byte of that block;
2. process_rr's `resolve` for A rr B, where B holds a both-scoped entry
   naming ey, one naming hx and one without channels, does not apply B's
   hx and all-channel entries as remote and leave out the ey one, counting
   `remote_left_out_channels` 1, or its "masks:" line does not end with
   "B 1 naming no magnetic channel left out)";
3. the per-row runs are wrong: for A rr B with A declaring channels ex, ey,
   hx, hy (rows ex and ey), A's entries [ex], [ey, hx] and one without
   channels, and B's both-scoped entry, `channel_runs` is not [ex with 4
   masks, ey with 3 masks and the base], the sidecar's `channel_runs` not
   the same with counts, its `masks` entries do not carry `channels` as
   masks.yaml does (a list, or no key for every channel), or the
   resolution does not print "mask runs: ex 4; ey 3 (base)"; an [hz] entry on rows ex and ey is not left out and
   counted as `local_left_out_channels` 1; `row_runs` on rows ex, ey, hz
   does not put ey and hz in one run, does not give the base to the run
   with the fewest masks, or on a tie to the earlier row; or with no
   channel entry does not give one run holding the masks list unchanged,
   in order;
4. `merge_rows` of two synthetic TFs, the ex row from run 1 (periods 1, 2,
   4, 8 s) and ey and hz from run 2, the base (periods 1, 2, 8, 16 s), does
   not give periods 1, 2, 4, 8, 16 s; row ex of the transfer function and
   its error not run 1's, NaN at 16 s; rows ey and hz not run 2's, NaN at
   4 s; row and column ex of the residual covariance not run 1's apart
   from the ex-ey and ex-hz terms, which come from run 2 as the later run;
   the inverse signal power and the station not run 2's; or the merged TF
   does not write an EDI that reads back with the five periods;
5. `stack_impedance` on a hand-made store with an [ex] mask over two of
   eight minute bins does not give row ex equal to the stack with that
   mask on every channel, row ey equal to the stack with no mask (to
   1e-12), `n_windows_row` those two stacks' window counts, or the
   all-channel counts; `masked_chunks` does not mark those bins for
   channel None and ex, and none for ey;
6. the history is wrong: `retire_masks` of C19's night entries does not
   return them with retired {on, why}, leave "C19: []" in masks.yaml and
   C22's block and the header byte for byte, or write them to
   masks_history.yaml under its header with their keys; a second retire
   does not append after them; `restore_masks` does not move one back
   without `retired`, leaving the other in the history; a temporary file
   is left in the folder; `replace_text` lets the target change before
   its `os.replace`, or, when `os.replace` fails, changes the target or
   leaves the temporary file; scripts/retire_masks.py's --dry-run changes
   a byte of either file, its AND-ed selectors (--found-by night
   --overlapping) do not pick exactly the one entry, it does not print
   the entry line and the counts, does not exit 2 when nothing matches or
   --why is missing, or --restore does not move the entry back;
7. a mutation does not trip: `masks_for_row` giving every mask to every
   row must trip criterion 3's runs, and `stored` writing "channels: all"
   must trip criterion 1's byte check.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from loguru import logger  # noqa: E402

import crust.masks as cmasks  # noqa: E402
from crust.crosspower import SUMS, WindowStore, bin_windows, masked_chunks, stack_impedance  # noqa: E402
from crust.masks import (  # noqa: E402
    HEADER, HISTORY_HEADER, history_path, load_history, load_masks, masks_path, normalise, remote_channel_split,
    replace_text, restore_masks, retire_masks, save_masks,
)

logger.remove()
logger.add(sys.stderr, level="WARNING")

T0 = pd.Timestamp("2023-09-22T00:00:00", tz="UTC")
STARTED = dt.datetime(2026, 9, 27, 9, 0, 0, tzinfo=dt.timezone.utc)
# the block an entry without channels was written as before the key existed, stated here
BLOCK_X = ("X:\n"
           "- start: '2023-09-22T01:00:00Z'\n"
           "  end: '2023-09-22T01:30:00Z'\n"
           "  bands: all\n"
           "  reason: ey burst\n"
           "  found_by: time\n"
           "  scope: local\n")


def entry(h0: float, h1: float, reason: str, bands="all", scope: str | None = None, channels=None,
          found_by: str = "time") -> dict:
    """Build one masks.yaml entry from hour h0 to hour h1 after T0; scope and channels left out when None."""
    out = {"start": (T0 + pd.Timedelta(hours=h0)).isoformat().replace("+00:00", "Z"),
           "end": (T0 + pd.Timedelta(hours=h1)).isoformat().replace("+00:00", "Z"),
           "bands": bands, "reason": reason, "found_by": found_by}
    if scope is not None:
        out["scope"] = scope
    if channels is not None:
        out["channels"] = channels
    return out


def make_survey(root: Path, masks: dict, channels_a=None) -> Path:
    """Write a two-site survey.yaml (A declaring `channels_a`), an empty filters.yaml and masks.yaml."""
    sites = {s: {"latitude": 31.0 + 0.045 * k, "longitude": -5.5, "start": "2023-09-22T00:00:00Z",
                 "end": "2023-09-23T00:00:00Z"} for k, s in enumerate(("A", "B"))}
    if channels_a:
        sites["A"]["channels"] = list(channels_a)
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text("{}\n", encoding="utf-8")
    (root / "masks.yaml").write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")
    return root / "survey.yaml"


def load_script(name: str):
    """Import scripts/<name>.py as a module."""
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger.remove()  # after the script's imports (mth5 adds its own sink)
    logger.add(sys.stderr, level="WARNING")
    return module


PROCESS_RR = load_script("process_rr")
RETIRE = load_script("retire_masks")


def resolved(survey_yaml: Path, local: str, remote: str, *extra):
    """Resolve local rr remote; return (resolution, sidecar, printed lines)."""
    args = PROCESS_RR.build_parser().parse_args([str(survey_yaml), local, remote, *extra])
    res = PROCESS_RR.resolve(args, STARTED)
    edi = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
    sidecar = PROCESS_RR.build_sidecar(res, args, STARTED, STARTED, edi, edi.with_suffix(".png"), {}, [])
    json.loads(json.dumps(sidecar, default=str))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        PROCESS_RR.print_resolution(res)
    return res, sidecar, out.getvalue().splitlines()


# ---------------------------------------------------------------- 1

def check_bytes(tmp: Path) -> None:
    """Criterion 1's file checks: the channels line, the key left out, byte-stable blocks."""
    survey_yaml = tmp / "survey.yaml"
    survey_yaml.write_text("name: x\n", encoding="utf-8")
    path = masks_path(survey_yaml)
    if path.exists():
        path.unlink()
    save_masks(survey_yaml, "X", [entry(1, 1.5, "ey burst")])
    text = path.read_text(encoding="utf-8")
    assert text == HEADER + BLOCK_X, f"the block of an entry without channels is not BLOCK_X: {text!r}"
    save_masks(survey_yaml, "X", [entry(1, 1.5, "ey burst")])
    assert path.read_text(encoding="utf-8") == text, "re-saving the same list changed the file"
    save_masks(survey_yaml, "Y", [entry(2, 3, "ex night", channels=["ex"]), entry(4, 5, "whole")])
    text2 = path.read_text(encoding="utf-8")
    assert text2.startswith(HEADER + BLOCK_X), "saving Y changed X's block"
    y_block = text2[len(HEADER + BLOCK_X):]
    assert y_block.count("  channels: [ex]\n") == 1 and y_block.count("channels") == 1, y_block
    got = [(m["reason"], m["channels"]) for m in load_masks(survey_yaml, "Y")]
    assert got == [("ex night", ["ex"]), ("whole", "all")], got


def test_normalise_and_file() -> None:
    assert normalise(entry(1, 2, "x"))["channels"] == "all"
    assert normalise(entry(1, 2, "x", channels=["EY", "ex"]))["channels"] == ["ex", "ey"]
    for bad in (["ez"], [], "ex"):
        try:
            normalise(entry(1, 2, "x", channels=bad))
        except ValueError as exc:
            assert "channels" in str(exc), exc
        else:
            raise AssertionError(f"channels {bad!r} accepted")
    with tempfile.TemporaryDirectory() as tmp:
        check_bytes(Path(tmp))
    print("  no key -> all; [EY, ex] -> [ex, ey]; [ez], [] and 'ex' refused; channels: [ex] written, the key left "
          "out otherwise; an entry without channels writes BLOCK_X byte for byte, re-saving and other sites "
          "leave it")


# ---------------------------------------------------------------- 2

def test_remote_channels() -> None:
    masks = {"A": [entry(1, 1.5, "A own")],
             "B": [entry(2, 2.5, "B ey burst", scope="both", channels=["ey"]),
                   entry(3, 3.5, "B hx spike", scope="both", channels=["hx"]),
                   entry(4, 4.5, "B mains", scope="both")]}
    applied, left = remote_channel_split([normalise(m) for m in masks["B"]])
    assert [m["reason"] for m in applied] == ["B hx spike", "B mains"] and [m["reason"] for m in left] == \
        ["B ey burst"], (applied, left)
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = make_survey(Path(tmp), masks)
        res, sidecar, lines = resolved(survey_yaml, "A", "B")
        assert [m["reason"] for m in res["masks_remote"]] == ["B hx spike", "B mains"], res["masks_remote"]
        assert sidecar["mask_counts"]["remote_left_out_channels"] == 1, sidecar["mask_counts"]
        assert sidecar["mask_counts"]["remote"] == 2, sidecar["mask_counts"]
        line = next(ln for ln in lines if ln.startswith("masks:"))
        assert line.endswith("B 1 naming no magnetic channel left out)"), line
    print(f"  B's [ey] entry left out as a remote, its [hx] and all-channel ones applied; {line!r}")


# ---------------------------------------------------------------- 3

ROWS_MASKS = {"A": [entry(1, 1.5, "A ex night", channels=["ex"]),
                    entry(2, 2.5, "A ey and hx", channels=["ey", "hx"]),
                    entry(3, 3.5, "A whole")],
              "B": [entry(4, 4.5, "B mains", scope="both")]}


def check_runs(survey_yaml: Path) -> str:
    """Criterion 3's resolve checks; return the "mask runs:" line."""
    res, sidecar, lines = resolved(survey_yaml, "A", "B")
    runs = [(r["channels"], [m["reason"] for m in r["masks"]], r["base"]) for r in res["channel_runs"]]
    assert runs == [(["ex"], ["A ex night", "A ey and hx", "A whole", "B mains"], False),
                    (["ey"], ["A ey and hx", "A whole", "B mains"], True)], runs
    assert sidecar["channel_runs"] == [{"channels": ["ex"], "masks": 4, "base": False},
                                       {"channels": ["ey"], "masks": 3, "base": True}], sidecar["channel_runs"]
    line = next(ln for ln in lines if ln.startswith("mask runs:"))
    assert line == "mask runs: ex 4; ey 3 (base)", line
    keys = {m["reason"]: m.get("channels") for m in sidecar["masks"]}
    assert keys == {"A ex night": ["ex"], "A ey and hx": ["ey", "hx"], "A whole": None, "B mains": None}, keys
    return line


def test_row_runs() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = make_survey(Path(tmp), ROWS_MASKS, channels_a=["ex", "ey", "hx", "hy"])
        line = check_runs(survey_yaml)
        hz = {**ROWS_MASKS, "A": ROWS_MASKS["A"] + [entry(5, 5.5, "A hz", channels=["hz"])]}
        (Path(tmp) / "masks.yaml").write_text(yaml.safe_dump(hz, sort_keys=False), encoding="utf-8")
        res, sidecar, _lines = resolved(survey_yaml, "A", "B")
        assert sidecar["mask_counts"]["local_left_out_channels"] == 1, sidecar["mask_counts"]
        assert "A hz" not in [m["reason"] for r in res["channel_runs"] for m in r["masks"]], res["channel_runs"]
    ex, ey, whole = (normalise(m) for m in (entry(1, 2, "ex", channels=["ex"]), entry(3, 4, "ey", channels=["ey"]),
                                             entry(5, 6, "whole")))
    runs, left = PROCESS_RR.row_runs([ex, whole], ["ex", "ey", "hz"])
    assert [(r["channels"], len(r["masks"]), r["base"]) for r in runs] == [(["ex"], 2, False),
                                                                            (["ey", "hz"], 1, True)], runs
    runs, _ = PROCESS_RR.row_runs([ex, ey], ["ex", "ey", "hz"])
    assert [(r["channels"], r["base"]) for r in runs] == [(["ex"], False), (["ey"], False), (["hz"], True)], runs
    runs, _ = PROCESS_RR.row_runs([ex, ey], ["ex", "ey"])
    assert [(r["channels"], r["base"]) for r in runs] == [(["ex"], True), (["ey"], False)], runs
    plain = [whole, normalise(entry(0, 0.5, "first"))]
    runs, left = PROCESS_RR.row_runs(plain, ["ex", "ey", "hz"])
    assert len(runs) == 1 and runs[0]["masks"] == plain and runs[0]["base"] and not left, runs
    runs, left = PROCESS_RR.row_runs([], ["ex", "ey"])
    assert runs == [{"channels": ["ex", "ey"], "masks": [], "base": True}] and left == [], runs
    print(f"  {line!r}; an [hz] entry on rows ex, ey left out (local_left_out_channels 1); ey and hz share a run; "
          "base to the fewest, a tie to the earlier row; no channel entry: one run, the list unchanged")


# ---------------------------------------------------------------- 4

def synthetic_tf(periods, offset: float, station: str):
    """Build an mt_metadata TF on `periods` whose every value encodes (offset, period index, output, input)."""
    from mt_metadata.transfer_functions.core import TF

    tf = TF()
    tf.station = station
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


def test_merge_rows() -> None:
    p1, p2 = [1.0, 2.0, 4.0, 8.0], [1.0, 2.0, 8.0, 16.0]
    tf1, tf2 = synthetic_tf(p1, 1000.0, "RUN1"), synthetic_tf(p2, 5000.0, "RUN2")
    runs = [{"channels": ["ex"], "masks": [], "base": False}, {"channels": ["ey", "hz"], "masks": [], "base": True}]
    merged = PROCESS_RR.merge_rows([tf1, tf2], runs)
    ds, d1, d2 = merged._transfer_function, tf1._transfer_function, tf2._transfer_function
    periods = np.asarray(ds["period"].values, dtype=float)
    assert periods.tolist() == [1.0, 2.0, 4.0, 8.0, 16.0], periods

    def at(d, var, p, **sel):
        return d[var].sel(period=p, **sel).values

    for p in periods:
        for var in ("transfer_function", "transfer_function_error"):
            got_ex = at(ds, var, p, output="ex", input=["hx", "hy"])
            want_ex = at(d1, var, p, output="ex", input=["hx", "hy"]) if p in p1 else np.full(2, np.nan)
            np.testing.assert_array_equal(got_ex, want_ex, err_msg=f"{var} ex at {p} s")
            for row in ("ey", "hz"):
                got = at(ds, var, p, output=row, input=["hx", "hy"])
                want = at(d2, var, p, output=row, input=["hx", "hy"]) if p in p2 else np.full(2, np.nan)
                np.testing.assert_array_equal(got, want, err_msg=f"{var} {row} at {p} s")
        cov = "residual_covariance"
        if p in p1:
            for other in ("ex", "hx", "hy"):
                assert at(ds, cov, p, output="ex", input=other) == at(d1, cov, p, output="ex", input=other), (p, other)
                assert at(ds, cov, p, output=other, input="ex") == at(d1, cov, p, output=other, input="ex"), (p, other)
        if p in p2:
            for a, b in (("ex", "ey"), ("ey", "ex"), ("ex", "hz"), ("hz", "ex"), ("ey", "hz"), ("hz", "hz")):
                assert at(ds, cov, p, output=a, input=b) == at(d2, cov, p, output=a, input=b), (p, a, b)
            np.testing.assert_array_equal(at(ds, "inverse_signal_power", p), at(d2, "inverse_signal_power", p))
        else:
            assert np.isnan(at(ds, "inverse_signal_power", p)).all(), p
    assert merged.station == "RUN2", merged.station
    with tempfile.TemporaryDirectory() as tmp:
        from mt_metadata.transfer_functions.core import TF

        edi = Path(tmp) / "merged.edi"
        merged.write(fn=edi, file_type="edi")
        back = TF(fn=str(edi))
        back.read()
        assert np.allclose(sorted(np.asarray(back.period, dtype=float)), periods, rtol=1e-4), back.period
    print("  periods 1-16 s joined; ex from run 1 (NaN at 16 s), ey and hz from run 2 (NaN at 4 s); residual "
          "covariance rows and columns by run, the ex-ey term from run 2; isp and station from the base; "
          "the EDI reads back with 5 periods")


# ---------------------------------------------------------------- 5

def tiny_store(n_bins: int = 8, per_bin: int = 12, seed: int = 5) -> WindowStore:
    """Return a hand-made store: 1 Hz, one binned level, one band, `per_bin` windows per minute bin.

    E = Z H + noise, R = H + noise, as tests/crosspower_unit.py's `tiny_store` builds it.
    """
    rng = np.random.default_rng(seed)
    z = np.array([[0.3, 2.0], [-1.5, -0.2]], dtype=complex)
    cn = lambda *shape: rng.standard_normal(shape) + 1j * rng.standard_normal(shape)  # noqa: E731
    sums = {name: [] for name in SUMS}
    for _ in range(n_bins):
        h = cn(per_bin, 2)
        r, e = h + 0.5 * cn(per_bin, 2), h @ z.T + 0.5 * cn(per_bin, 2)
        outer = lambda a, b: np.einsum("wi,wj->ij", a, np.conj(b))[None]  # noqa: E731
        sums["er"].append(outer(e, r))
        sums["hr"].append(outer(h, r))
        sums["eh"].append(outer(e, h))
        sums["hh"].append(outer(h, h))
        sums["ee"].append((np.abs(e) ** 2).sum(axis=0)[None])
    n_used = np.full(n_bins, per_bin, dtype=np.int64)
    level = {"level": 0, "binned": True, "win": 16, "win_b": 16, "hop_b": 8, "bands": np.array([0]),
             "n_harm": np.array([8]), "starts": np.arange(n_bins, dtype=np.int64) * 60, "span_n": 60,
             "n_used": n_used, "n_possible": n_used.copy(), **{k: np.array(v) for k, v in sums.items()}}
    return WindowStore("T", "TR", 1.0, 4, 0, 60 * n_bins, 60, 0, np.array([0]), np.array([0.1]),
                       np.array([0.2]), [level], {}, 0, [], 600, 1, 0.0)


def test_stack_rows() -> None:
    result = bin_windows(tiny_store(), 60.0)
    epoch = pd.Timestamp(0, tz="UTC")
    span = {"start": epoch + pd.Timedelta(seconds=120), "end": epoch + pd.Timedelta(seconds=240),
            "bands": "all", "reason": "ex burst", "found_by": "time"}
    ex_only, whole = {**span, "channels": ["ex"]}, dict(span)
    by_row, all_ch, none = (stack_impedance(result, m) for m in ([ex_only], [whole], []))
    np.testing.assert_allclose(by_row["z"][:, 0], all_ch["z"][:, 0], rtol=1e-12, atol=0)
    np.testing.assert_allclose(by_row["z"][:, 1], none["z"][:, 1], rtol=1e-12, atol=0)
    np.testing.assert_allclose(by_row["z_err"][:, 0], all_ch["z_err"][:, 0], rtol=1e-12, atol=0)
    np.testing.assert_allclose(by_row["z_err"][:, 1], none["z_err"][:, 1], rtol=1e-12, atol=0)
    assert not np.allclose(all_ch["z"][:, 1], none["z"][:, 1], rtol=1e-6), "the mask changed nothing: no test"
    assert by_row["n_windows_row"].tolist() == [[int(all_ch["n_windows"][0]), int(none["n_windows"][0])]], \
        by_row["n_windows_row"]
    assert by_row["n_windows"].tolist() == all_ch["n_windows"].tolist() == [72], by_row["n_windows"]
    marks = {c: masked_chunks(result, [ex_only], 0, c).tolist() for c in (None, "ex", "ey")}
    want = [0, 0, 2, 2, 0, 0, 0, 0]
    assert marks == {None: want, "ex": want, "ey": [0] * 8}, marks
    print(f"  [ex] mask over bins 2-3: row ex = the all-channel stack's, row ey = the unmasked stack's; windows "
          f"per row {by_row['n_windows_row'].tolist()}; masked_chunks None/ex {want}, ey clear")


# ---------------------------------------------------------------- 6

C19 = [entry(18.8, 30.2, "night ex", bands=[0.2, 5000.0], found_by="night"),
       entry(43.2, 54.2, "second night ex", bands=[0.2, 5000.0], found_by="night"),
       entry(34.0, 34.5, "hand cut")]
C22 = [entry(33.7, 33.8, "C22 transient", bands=[0.004, 5000.0], scope="both")]


def history_survey(tmp: Path) -> Path:
    """Write a survey folder whose masks.yaml holds a comment and C19 and C22; return survey.yaml."""
    survey_yaml = tmp / "survey.yaml"
    survey_yaml.write_text("name: x\n", encoding="utf-8")
    masks_path(survey_yaml).write_text("# hand comment\n", encoding="utf-8")
    save_masks(survey_yaml, "C19", C19)
    save_masks(survey_yaml, "C22", C22)
    return survey_yaml


def leftovers(folder: Path) -> list[str]:
    """Return the temporary files `replace_text` could leave in a folder."""
    return sorted(p.name for p in folder.iterdir() if p.name.endswith(".tmp"))


def test_history() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        survey_yaml = history_survey(tmp)
        before = masks_path(survey_yaml).read_text(encoding="utf-8")
        c22_block = before[before.index("C22:"):]
        retired = retire_masks(survey_yaml, "C19", lambda m: m["found_by"] == "night", "replaced by channels [ex]",
                               on="2026-09-27")
        assert [m["reason"] for m in retired] == ["night ex", "second night ex"], retired
        assert all(m["retired"] == {"on": "2026-09-27", "why": "replaced by channels [ex]"} for m in retired)
        after = masks_path(survey_yaml).read_text(encoding="utf-8")
        assert after.startswith("# hand comment\n") and after.endswith(c22_block), after
        assert [m["reason"] for m in load_masks(survey_yaml, "C19")] == ["hand cut"], after
        history = history_path(survey_yaml).read_text(encoding="utf-8")
        assert history.startswith(HISTORY_HEADER) and "  retired:\n    'on': '2026-09-27'\n" in history, history
        assert "  bands: [0.2, 5000.0]\n" in history and "  found_by: night\n" in history, history
        retire_masks(survey_yaml, "C19", lambda m: m["reason"] == "hand cut", "a test", on="2026-09-28")
        assert "C19: []\n" in masks_path(survey_yaml).read_text(encoding="utf-8")
        assert [m["reason"] for m in load_history(survey_yaml, "C19")] == ["night ex", "second night ex",
                                                                           "hand cut"]
        back = restore_masks(survey_yaml, "C19", lambda m: m["reason"] == "second night ex")
        assert [m["reason"] for m in back] == ["second night ex"] and "retired" not in back[0], back
        assert [m["reason"] for m in load_masks(survey_yaml, "C19")] == ["second night ex"]
        assert [m["reason"] for m in load_history(survey_yaml, "C19")] == ["night ex", "hand cut"]
        hand = history_path(survey_yaml).read_text(encoding="utf-8").replace("'on':", "on:")
        history_path(survey_yaml).write_text(hand, encoding="utf-8")  # a hand edit, `on` unquoted
        assert [m["retired"]["on"] for m in load_history(survey_yaml, "C19")] == ["2026-09-27", "2026-09-28"]
        assert "retired" not in masks_path(survey_yaml).read_text(encoding="utf-8")
        assert leftovers(tmp) == [], leftovers(tmp)

        # replace_text: the target keeps its old text until os.replace, and a failed replace changes nothing
        target = masks_path(survey_yaml)
        old = target.read_text(encoding="utf-8")
        real_replace = cmasks.os.replace
        seen = []

        def watching(src, dst):
            seen.append((Path(src).parent == Path(dst).parent, Path(dst).read_text(encoding="utf-8") == old,
                         Path(src).read_text(encoding="utf-8")))
            return real_replace(src, dst)

        def failing(src, dst):
            raise OSError("disk full")

        cmasks.os.replace = watching
        try:
            replace_text(target, "NEW: []\n")
        finally:
            cmasks.os.replace = real_replace
        assert seen == [(True, True, "NEW: []\n")], seen
        assert target.read_text(encoding="utf-8") == "NEW: []\n"
        cmasks.os.replace = failing
        try:
            replace_text(target, "LOST: []\n")
        except OSError:
            pass
        else:
            raise AssertionError("a failing os.replace was not raised")
        finally:
            cmasks.os.replace = real_replace
        assert target.read_text(encoding="utf-8") == "NEW: []\n" and leftovers(tmp) == [], leftovers(tmp)
    print("  retire: C19's two night entries to the history with retired {on, why}, C22 and the comment byte for "
          "byte; a second retire appended, C19: [] kept; restore moves one back without retired; no temp file; "
          "the target unchanged until os.replace, and after a failed replace")


def run_script(*argv) -> tuple[int, str, str]:
    """Run scripts/retire_masks.py's main in-process; return (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = RETIRE.main([str(a) for a in argv])
    return code, out.getvalue(), err.getvalue()


def test_script() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        survey_yaml = history_survey(tmp)
        snapshot = lambda: (masks_path(survey_yaml).read_bytes(),  # noqa: E731
                            history_path(survey_yaml).read_bytes() if history_path(survey_yaml).exists() else b"")
        first = snapshot()
        pick = ["--found-by", "night", "--overlapping", "2023-09-23T19:00:00Z..2023-09-23T20:00:00Z"]
        code, out, _ = run_script(survey_yaml, "C19", *pick, "--why", "test", "--dry-run")
        assert code == 0 and snapshot() == first, (code, out)
        lines = out.splitlines()
        assert lines[1].startswith("  2023-09-23T19:12:00Z  2023-09-24T06:12:00Z  bands [0.2, 5000]  "
                                   "found_by night  scope local  channels all  second night ex"), lines
        assert lines[-1] == ("C19: masks.yaml 3 -> 2, masks_history.yaml 0 -> 1 (dry run: nothing moved)"), lines
        code, out, _ = run_script(survey_yaml, "C19", *pick, "--why", "test")
        assert code == 0 and out.splitlines()[-1] == "C19: masks.yaml 3 -> 2, masks_history.yaml 0 -> 1", out
        assert [m["reason"] for m in load_history(survey_yaml, "C19")] == ["second night ex"]
        code, out, _ = run_script(survey_yaml, "C19", "--found-by", "gate", "--why", "test")
        assert code == 2 and "nothing moved" in out, (code, out)
        code, _out, err = run_script(survey_yaml, "C19", "--found-by", "night")
        assert code == 2 and "--why" in err, (code, err)
        code, out, _ = run_script(survey_yaml, "C19", "--restore", "--reason-contains", "SECOND")
        assert code == 0 and out.splitlines()[-1] == "C19: masks.yaml 2 -> 3, masks_history.yaml 1 -> 0", out
        assert [m["reason"] for m in load_masks(survey_yaml, "C19")] == ["night ex", "hand cut", "second night ex"]
        assert leftovers(tmp) == []
    print("  --dry-run moves nothing; --found-by night --overlapping picks the second night alone, printed on one "
          "line with the counts; no match and a missing --why exit 2; --restore moves it back")


# ---------------------------------------------------------------- 7

def test_mutations() -> None:
    saved_row = PROCESS_RR.masks_for_row
    PROCESS_RR.masks_for_row = lambda masks, row: [normalise(m) for m in masks or []]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            survey_yaml = make_survey(Path(tmp), ROWS_MASKS, channels_a=["ex", "ey", "hx", "hy"])
            try:
                check_runs(survey_yaml)
            except AssertionError as exc:
                print(f"  masks_for_row ignoring channels: criterion 3 trips ({str(exc)[:90]})")
            else:
                raise AssertionError("criterion 3 held with every mask given to every row")
    finally:
        PROCESS_RR.masks_for_row = saved_row
    saved_stored = cmasks.stored
    cmasks.stored = lambda m: {**saved_stored(m), "channels": normalise(m)["channels"]}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                check_bytes(Path(tmp))
            except AssertionError as exc:
                print(f"  stored writing channels: all: criterion 1 trips ({str(exc)[:70]})")
            else:
                raise AssertionError("criterion 1 held with channels: all written")
    finally:
        cmasks.stored = saved_stored


if __name__ == "__main__":
    tests = [test_normalise_and_file, test_remote_channels, test_row_runs, test_merge_rows, test_stack_rows,
             test_history, test_script, test_mutations]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  mask_channels_unit ({len(tests)} tests)")
