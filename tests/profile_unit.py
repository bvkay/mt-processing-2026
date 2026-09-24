# -*- coding: utf-8 -*-
"""
Unit test for scripts/profile_run.py

Checks the log-phase parser on an excerpt of a real campaign log, the mark
partition and self times on synthetic marks, the sampler on a child
process, the trace-stage markers on a stub pipeline and the tracemalloc diff
table. Runs without an archive or an aurora run.

Usage:
    python tests/profile_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** the parser, given 28 lines cut from a real campaign log
(s3_C18_rr-C19_boxcar.log, loguru colour codes and a two-line
message included; only the paths shortened), does not return exactly the 17
phases below in order, each within 0.01 s of the length worked out by hand
from the lines' own timestamps (L0 read 46.86 s, L0 STFT 156.01 s, L0 merge
3.18 s, L0 regression 212.55 s, ...), or the phases leave a gap or overlap;
or, on synthetic marks, an instant is not given to the innermost P mark
covering it (a nested "L0 STFT" inside "aurora (other)" must split it in two,
time before the first mark is "python start + imports", between marks
"(untracked)", after the last "exit"), or a mark's self time does not exclude
the mark nested in it; or the sampler, on a child that fills 400 MiB of numpy
array, sleeps 1.5 s between a pair of PROFMARK lines and exits, takes fewer
than 4 samples, sees a peak working set under 400 MiB (it missed the
allocation) or over 2 GiB, or the parsed "hold" phase is not 1.5 +- 0.3 s
long with a peak RSS of at least 400 MiB in the phase table; or, for the
trace stage, the marker wrapper installed on a stub pipeline (two levels,
each "read/decimate", "STFT" with a nested detrend, "regression" over two
bands for ex then ey) does not emit exactly the six phase spans L0 read TS,
L0 STFT, L0 regression, L1 decimate TS, L1 STFT, L1 regression in that
order, the eight band spans "L<n> band <T> s <ch>" in aurora's loop order
(channels outside bands), each band span holding its extraction, estimate
and set_tf and lying inside its level's regression, each detrend inside its
level's STFT; or the PROFMARK lines of the same run do not partition into
those phases; or, with viztracer installed, the spans do not reach the
trace on the "mtproc phases + counters" track with the stub's `stft` call
(MainThread) inside the "L0 STFT" span; or the tracemalloc diff table, on
two snapshots around a retained 16 MiB bytearray, a retained 1 MiB one and
a freed 32 MiB one, does not put the 16 MiB one first (+16 MiB to 1 kiB in
two blocks -- the bytearray object and its separate buffer -- at the
allocating line of `_stub_retained`, its caller in the chain) and the 1 MiB
one (`_stub_small`) second, or lists the freed one at all.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "src"))

import profile_run as pr  # noqa: E402

EXCERPT = "\n".join([
    '=== 2026-09-24T06:45:08+08:00 python.exe process_rr.py survey.yaml C18 C19 --taper boxcar --tag lineC-boxcar',
    'started: 2026-09-24T06:45:11.156306+08:00',
    '\x1b[1m2026-09-24T06:45:12.056381+0800 | INFO | __main__ | main | line: 475 | C18: Ex 55.0 m @ 0.0 deg, Ey 45.0 m @ 90.0 deg, timing None\x1b[0m',
    '\x1b[1m2026-09-24T06:45:13.928145+0800 | INFO | mtproc.process | process_station | line: 253 | aurora: C18 RR C19\x1b[0m',
    '\x1b[1m2026-09-24T06:45:14.112994+0800 | INFO | aurora.pipelines.transfer_function_kernel | valid_decimations | line: 413 | After validation there are 10 valid decimation levels\x1b[0m',
    '\x1b[1m2026-09-24T06:46:00.814290+0800 | INFO | mth5.processing.kernel_dataset | initialize_dataframe_for_processing | line: 1310 | Dataset dataframe initialized successfully, updated metadata.\x1b[0m',
    '\x1b[1m2026-09-24T06:46:00.974900+0800 | INFO | aurora.pipelines.transfer_function_kernel | update_dataset_df | line: 156 | Dataset Dataframe Updated for decimation level 0 Successfully\x1b[0m',
    '\x1b[1m2026-09-24T06:46:03.761014+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:46:06.686106+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:47:22.658011+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:48:36.984576+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:48:40.164884+0800 | INFO | aurora.pipelines.feature_weights | extract_features | line: 43 | Features could not be accessed from MTH5 -- ',
    'Calculating features on the fly (development only)\x1b[0m',
    '\x1b[1m2026-09-24T06:48:40.168581+0800 | INFO | aurora.time_series.frequency_band_helpers | get_band_for_tf_estimate | line: 45 | Accessing band 0.017145s  (58.324839Hz)\x1b[0m',
    '\x1b[1m2026-09-24T06:52:12.718614+0800 | INFO | aurora.pipelines.transfer_function_kernel | update_dataset_df | line: 137 | DECIMATION LEVEL 1\x1b[0m',
    '\x1b[1m2026-09-24T06:52:36.875990+0800 | INFO | aurora.pipelines.transfer_function_kernel | update_dataset_df | line: 156 | Dataset Dataframe Updated for decimation level 1 Successfully\x1b[0m',
    '\x1b[1m2026-09-24T06:52:38.085789+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:52:39.101969+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:52:56.876571+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:53:14.666794+0800 | INFO | aurora.time_series.spectrogram_helpers | save_fourier_coefficients | line: 341 | Skip saving FCs. dec_level_config.save_fc =  False\x1b[0m',
    '\x1b[1m2026-09-24T06:53:16.580611+0800 | INFO | aurora.pipelines.feature_weights | extract_features | line: 43 | Features could not be accessed from MTH5 -- ',
    'Calculating features on the fly (development only)\x1b[0m',
    '\x1b[1m2026-09-24T06:53:58.192049+0800 | INFO | aurora.pipelines.transfer_function_kernel | update_dataset_df | line: 137 | DECIMATION LEVEL 2\x1b[0m',
    '\x1b[1m2026-09-24T06:54:03.372738+0800 | INFO | aurora.pipelines.transfer_function_kernel | update_dataset_df | line: 156 | Dataset Dataframe Updated for decimation level 2 Successfully\x1b[0m',
    "\x1b[1m2026-09-24T06:54:49.548037+0800 | INFO | aurora.pipelines.process_mth5 | process_mth5_legacy | line: 230 | type(tf_cls): <class 'mt_metadata.transfer_functions.core.TF'>\x1b[0m",
    '\x1b[1m2026-09-24T06:54:49.821920+0800 | INFO | mtproc.process | process_station | line: 265 | wrote tf\\C18_rr-C19_20260924-0645_lineC-boxcar.edi\x1b[0m',
    '\x1b[1m2026-09-24T06:54:50.279523+0800 | INFO | __main__ | main | line: 538 | wrote tf\\C18_rr-C19_20260924-0645_lineC-boxcar_vs_lemimt.png\x1b[0m',
    '\x1b[1m2026-09-24T06:54:50.347061+0800 | INFO | __main__ | main | line: 546 | wrote tf\\C18_rr-C19_20260924-0645_lineC-boxcar.json\x1b[0m',
])

# (phase, seconds), by hand from the excerpt's own timestamps
EXPECTED = [
    ("python start + imports", 3.156306),  # "=== 06:45:08" header -> "started: 06:45:11.156306"
    ("survey load + archive status", 0.900075),
    ("archives + run summary + kernel dataset + config", 1.871764),
    ("aurora setup", 0.184849),
    ("L0 read TS", 46.861906),  # valid_decimations 06:45:14.112994 -> level 0 updated 06:46:00.974900
    ("L0 STFT", 156.009676),  # -> the 4th "Skip saving FCs", 06:48:36.984576
    ("L0 merge STFTs", 3.180308),  # -> extract_features 06:48:40.164884
    ("L0 regression", 212.553730),  # -> DECIMATION LEVEL 1, 06:52:12.718614
    ("L1 decimate", 24.157376),
    ("L1 STFT", 37.790804),
    ("L1 merge STFTs", 1.913817),
    ("L1 regression", 41.611438),
    ("L2 decimate", 5.180689),
    ("L2 STFT", 46.175299),  # the excerpt jumps from level 2 straight to type(tf_cls)
    ("close archives + EDI write", 0.273883),
    ("quadrants + comparison figure", 0.457603),
    ("sidecar", 0.067538),
]


def test_rr_log_phases() -> None:
    phases = pr.phases_from_rr_log(pr.parse_log(EXCERPT), None, None)
    names = [p["name"] for p in phases]
    assert names == [n for n, _ in EXPECTED], names
    for p, (name, secs) in zip(phases, EXPECTED):
        assert abs((p["t1"] - p["t0"]) - secs) < 0.01, (name, p["t1"] - p["t0"], secs)
    for a, b in zip(phases[:-1], phases[1:]):
        assert a["t1"] == b["t0"], ("gap or overlap", a, b)
    print(f"  {len(phases)} phases from the real excerpt: L0 read {phases[4]['t1'] - phases[4]['t0']:.2f} s, "
          f"STFT {phases[5]['t1'] - phases[5]['t0']:.2f} s, regression {phases[7]['t1'] - phases[7]['t0']:.2f} s")


def _marks(*rows):
    """Build mark events from (t, flag, kind, name) rows."""
    return [{"type": "mark", "t": t, "flag": f, "kind": k, "name": n} for t, f, k, n in rows]


def test_marks_partition_and_self_time() -> None:
    events = _marks((10.0, "B", "P", "survey load"), (11.0, "E", "P", "survey load"),
                    (12.0, "B", "P", "aurora (other)"), (13.0, "B", "P", "L0 STFT"),
                    (13.5, "B", "D", "stft: detrend"), (14.0, "E", "D", "stft: detrend"),
                    (15.0, "E", "P", "L0 STFT"), (16.0, "E", "P", "aurora (other)"))
    iv = pr.mark_intervals(events)
    got = [(p["name"], p["t0"], p["t1"]) for p in pr.phases_from_marks(iv, 9.0, 17.0)]
    want = [("python start + imports", 9.0, 10.0), ("survey load", 10.0, 11.0), ("(untracked)", 11.0, 12.0),
            ("aurora (other)", 12.0, 13.0), ("L0 STFT", 13.0, 15.0), ("aurora (other)", 15.0, 16.0),
            ("exit", 16.0, 17.0)]
    assert got == want, got
    det = pr.details_table(iv).set_index("name")
    assert abs(det.loc["L0 STFT", "total_s"] - 2.0) < 1e-9, det
    assert abs(det.loc["L0 STFT", "self_s"] - 1.5) < 1e-9, det
    assert abs(det.loc["aurora (other)", "self_s"] - 2.0) < 1e-9, det
    print("  nested marks: the innermost wins, gaps are named, self time excludes the nested mark")


CHILD = """
import sys, time
import numpy as np
a = np.ones(400 * 2**20 // 8)
sys.stderr.write(f"PROFMARK {time.time():.6f} B P hold" + chr(10)); sys.stderr.flush()
time.sleep(1.5)
sys.stderr.write(f"PROFMARK {time.time():.6f} E P hold" + chr(10)); sys.stderr.flush()
del a
time.sleep(0.4)
"""


def test_sampler_on_a_sleeping_child() -> None:
    with tempfile.TemporaryDirectory() as d:
        log = Path(d) / "child.log"
        samples, t0, t1, rc = pr.run_sampled([sys.executable, "-c", CHILD], log, interval=0.2)
        text = log.read_text()
    assert rc == 0, text
    assert len(samples) >= 4, len(samples)
    peak_mib = samples["rss"].max() / 2**20
    assert 400 <= peak_mib <= 2048, f"peak working set {peak_mib:.0f} MiB"
    phases = pr.phases_from_marks(pr.mark_intervals(pr.parse_log(text)), t0, t1)
    hold = [p for p in phases if p["name"] == "hold"]
    assert len(hold) == 1 and abs(hold[0]["t1"] - hold[0]["t0"] - 1.5) < 0.3, phases
    table = pr.phase_table(phases, samples, t0).set_index("phase")
    assert table.loc["hold", "peak_rss_gib"] * 1024 >= 400, table
    print(f"  sampler: {len(samples)} samples over {t1 - t0:.1f} s, peak {peak_mib:.0f} MiB; 'hold' "
          f"{hold[0]['t1'] - hold[0]['t0']:.2f} s at {table.loc['hold', 'peak_rss_gib'] * 1024:.0f} MiB")


STUB = "profile_unit_stub_pipeline"


def _stub_module():
    """Register a stub aurora-like pipeline module and its marker targets ("stubtest")."""
    import time
    import types

    mod = types.ModuleType(STUB)

    def update_dataset_df(i_dec_level):
        time.sleep(0.002)

    def detrend():
        time.sleep(0.002)

    def stft(tfk, i_dec_level):
        time.sleep(0.001)
        mod.detrend()
        time.sleep(0.001)

    def get_band(band, dec_level_config=None):
        return band

    def estimate():
        time.sleep(0.001)

    def set_tf():
        pass

    def regression(i_dec_level, bands):
        for _ch in ("ex", "ey"):  # aurora: channels outside, bands inside
            for band in bands:
                mod.get_band(band)
                mod.estimate()
                mod.set_tf()

    def pipeline(bands):
        for level in (0, 1):
            mod.update_dataset_df(i_dec_level=level)
            mod.stft(None, level)
            mod.regression(level, bands)

    for f in (update_dataset_df, detrend, stft, get_band, estimate, set_tf, regression, pipeline):
        setattr(mod, f.__name__, f)
    sys.modules[STUB] = mod
    pr.TARGETS["stubtest"] = [(STUB, "update_dataset_df", pr._read_or_decimate, "P"),
                              (STUB, "stft", "L{L} STFT", "P"), (STUB, "detrend", "stft: detrend", "D"),
                              (STUB, "regression", "L{L} regression", "P"),
                              (STUB, "get_band", "band: extraction", "D"),
                              (STUB, "estimate", "band: RME_RR.estimate", "D"), (STUB, "set_tf", "band: set_tf", "D")]
    return mod


def _stub_retained():
    return bytearray(16 * 2**20)


def _stub_small():
    return bytearray(2**20)


def _stub_freed():
    buf = bytearray(32 * 2**20)
    return len(buf)


def _inside(inner, outer):
    """Check whether span `inner` lies within span `outer`."""
    return outer["t0"] <= inner["t0"] and inner["t1"] <= outer["t1"]


def test_trace_markers_and_tm_diff() -> None:
    import inspect
    import io
    import json
    import re
    import types
    import tracemalloc

    mod = _stub_module()
    missing = pr.install_markers("stubtest")
    assert not [m for m in missing if STUB in m], missing
    bands = [types.SimpleNamespace(center_period=0.5), types.SimpleNamespace(center_period=2.0)]
    spans: list = []
    tracker = pr.PhaseTracker()
    real_stderr = sys.__stderr__
    sys.__stderr__ = buf = io.StringIO()
    try:
        pr._SINKS[:] = [pr.SpanSink(spans.append), tracker]
        t0 = __import__("time").time()
        mod.pipeline(bands)
        t1 = __import__("time").time()
    finally:
        pr._SINKS[:] = []
        sys.__stderr__ = real_stderr
    phases = [sp for sp in spans if sp["kind"] == "P"]
    want = ["L0 read TS", "L0 STFT", "L0 regression", "L1 decimate TS", "L1 STFT", "L1 regression"]
    assert [sp["name"] for sp in phases] == want, [sp["name"] for sp in phases]
    band_spans = [sp for sp in spans if sp["kind"] == "band"]
    want_bands = [f"L{lv} band {p:g} s {ch}" for lv in (0, 1) for ch in ("ex", "ey") for p in (0.5, 2.0)]
    assert [sp["name"] for sp in band_spans] == want_bands, [sp["name"] for sp in band_spans]
    details = [sp for sp in spans if sp["kind"] == "D"]
    for bs in band_spans:
        inner = [d["name"] for d in details if d["name"].startswith("band:") and _inside(d, bs)]
        assert inner == ["band: extraction", "band: RME_RR.estimate", "band: set_tf"], (bs["name"], inner)
        assert all(d["band"] == bs["band"] for d in details if d["name"].startswith("band:") and _inside(d, bs))
        reg = next(sp for sp in phases if sp["name"] == f"L{bs['level']} regression")
        assert _inside(bs, reg), bs
    for d in (d for d in details if d["name"] == "stft: detrend"):
        assert _inside(d, next(sp for sp in phases if sp["name"] == f"L{d['level']} STFT")), d
    marked = pr.phases_from_marks(pr.mark_intervals(pr.parse_log(buf.getvalue())), t0, t1, min_s=0.0)
    got = [pc["name"] for pc in marked if pc["name"] not in ("python start + imports", "(untracked)", "exit")]
    assert got == want, got
    print(f"  stub: {len(phases)} phase spans, {len(band_spans)} band spans, {len(details)} details; "
          f"PROFMARK lines partition into the same phases")

    try:
        from viztracer import VizTracer
    except ImportError:
        print("  viztracer not installed: the trace round trip is not checked")
    else:
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "stub.json"
            tr = VizTracer(tracer_entries=200000, ignore_c_function=False, min_duration=0, dump_raw=True,
                           verbose=0, output_file=str(out))
            pump = pr.VizPump(tr, interval=0.05)
            sys.__stderr__ = io.StringIO()
            try:
                pr._SINKS[:] = [pr.SpanSink(pump.emit, clock=tr.getts), pr.PhaseTracker()]
                pump.start()
                tr.start()
                mod.pipeline(bands)
            finally:
                pr._SINKS[:] = []
                sys.__stderr__ = real_stderr
                pump.halt.set()
                pump.join()
                tr.stop()
                tr.save()
            events = json.loads(out.read_text(encoding="utf-8"))["traceEvents"]
        names = {e["tid"]: e["args"]["name"] for e in events if e.get("ph") == "M" and e.get("name") == "thread_name"}
        track = [e for e in events if e.get("ph") == "X" and names.get(e.get("tid")) == pr.SPAN_TRACK]
        assert [e["name"] for e in track if e["cat"] == "P"] == want, [e["name"] for e in track]
        l0 = next(e for e in track if e["name"] == "L0 STFT")
        calls = [e for e in events if e.get("cat") == "fee" and names.get(e.get("tid")) == "MainThread"
                 and re.match(r"^(\S+\.)?stft \(", e["name"])]
        assert len(calls) == 2 and any(l0["ts"] <= c["ts"] and c["ts"] + c["dur"] <= l0["ts"] + l0["dur"]
                                       for c in calls), (l0, calls)
        assert any(e.get("ph") == "C" and e["name"] == "memory (GiB)" for e in events), "no RSS counter"
        print(f"  viztracer: {len(track)} spans on '{pr.SPAN_TRACK}', the stub's stft call inside 'L0 STFT'")

    tracemalloc.start(10)
    try:
        s0 = tracemalloc.take_snapshot()
        kept = _stub_retained()
        small = _stub_small()
        _stub_freed()
        s1 = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    lines, first = inspect.getsourcelines(_stub_retained)
    line = first + next(i for i, ln in enumerate(lines) if "bytearray" in ln)
    for table in (pr.tm_diff_table(s1, s0, "stub", 15), pr.tm_diff_table(pr.tm_group(s1), pr.tm_group(s0), "stub", 15)):
        top = table.iloc[0]
        assert top["site"] == f"profile_unit.py:{line}" and top["function"] == "_stub_retained", top.to_dict()
        assert 16.0 <= top["plus_mib"] <= 16.0 + 1 / 1024 and top["blocks"] == 2, top.to_dict()
        assert "test_trace_markers_and_tm_diff" in top["chain"], top["chain"]
        assert table.iloc[1]["function"] == "_stub_small" and 1.0 <= table.iloc[1]["plus_mib"] <= 1.0 + 1 / 1024, table
        assert "_stub_freed" not in set(table["function"]), table
    print(f"  tracemalloc diff: +{top['plus_mib']:.4f} MiB at {top['site']} ({top['function']}), "
          f"called from {top['chain'].split('  <-  ')[0]}; the 1 MiB one second; the freed 32 MiB absent")
    del kept, small


if __name__ == "__main__":
    tests = [test_rr_log_phases, test_marks_partition_and_self_time, test_sampler_on_a_sleeping_child,
             test_trace_markers_and_tm_diff]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  profile_unit ({len(tests)} tests)")
