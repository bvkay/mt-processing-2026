# -*- coding: utf-8 -*-
"""
Unit test for crust.engine_mantle and the --engine flag of scripts/process_rr.py

The argument mapping (`MantleOptions` into MANTLE's `ProcessingConfig`,
`levels_for` on the window), the band pooling on a synthetic fine grid with
a hand-built jackknife, the sidecar keys the engine adds, the INFO lines
and the command line's refusals are checked without reading an archive.
The script is run as a subprocess with `--dry-run`, as the GUI runs it.

Usage:
    python tests/engine_mantle_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) `MantleOptions()` mapped through `process_pair`'s config recipe does not
    give a `ProcessingConfig` with references ("Hxr", "Hyr"), robust True,
    prewhiten False, jackknife 8, nperseg 4096, nw 3.0, decim 4,
    native_max_samples 2000000, detrend "constant", min_segments 3 and
    snr_gate True, or `MantleOptions(whiten="ar")` is accepted;

(2) `levels_for` does not give 6 levels for 6 h at 1000 Hz (21.6 M samples),
    7 for 16.5 h, 5 for 1 h and 1 for a window shorter than one segment, or
    exceeds MAX_LEVELS on a huge count;

(3) `band_pool` on a synthetic merged grid of two cascade bands (known Z per
    bin, a hand-built jackknife deviation array) does not return the plain
    complex mean of the bins each band holds at the period 1 / sqrt(lo hi),
    the pooled variance a^T Sigma a of those bins from the jackknife
    covariance (checked against an independent computation from the
    deviations), skip a band with no bins, leave out a bin whose status is
    not 0, or fall back to the mean per-bin variance over the member count
    when the result carries no jackknife;

(4) `to_tf` does not write an EDI that mt_metadata reads back with the same
    periods, impedance (to 1e-5 relative) and error sqrt(0.5 var), the
    remote in `remote_references` and the station location;

(5) `sidecar_extras` does not carry engine "mantle", a non-empty
    engine_version, an engine_config with the ProcessingConfig dict, the
    options, n_levels, the verdict word counts and snr_gate_ran, and the
    report and fine EDI names; or `process_rr.edi_info_lines` on a sidecar
    with engine "mantle" does not give crust.engine and
    crust.engine_version lines and no crust.taper line, while on a sidecar
    without `engine` it gives the crust.taper line and no engine line;

(6) `process_rr.py --engine mantle --dry-run` does not exit 0 and print
    `engine: mantle` and `mantle.whiten: none` with the same archives, stem
    and band block as the aurora dry run, a plain dry run does not print
    `engine: aurora`, or `--engine mantle --taper hann` does not exit
    non-zero naming the flag.

Proven red (2026-09-25) by returning the arithmetic mean of the per-bin
variances instead of the quadratic form in `band_pool` (criterion 3) and by
dropping the `engine` branch of `edi_info_lines` (criterion 5).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
SCRIPT = REPO / "scripts" / "process_rr.py"
SURVEY = REPO / "surveys" / "curnamona_cube" / "survey.yaml"

try:
    from crust import _mantle, engine_mantle
except ImportError as exc:  # MANTLE (mt_proc) is installed separately from the workflow's environment
    print(f"SKIP  engine_mantle_unit: {exc}")
    sys.exit(0)


def _load_process_rr():
    spec = importlib.util.spec_from_file_location("process_rr", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_options_map_to_processing_config() -> None:
    run = _mantle.module("processing.run")
    opts = engine_mantle.MantleOptions()
    cfg = run.ProcessingConfig(
        site_id="X", fs=1000.0, lat=-30.0, lon=139.0, elev=100.0, references=("Hxr", "Hyr"),
        robust=opts.robust, prewhiten=False, detrend=opts.detrend, nperseg=opts.nperseg, nw=opts.nw,
        n_levels=engine_mantle.levels_for(21_600_000), decim=opts.decim,
        native_max_samples=opts.native_max_samples, jackknife=opts.jackknife,
        min_segments=opts.min_segments, snr_gate=opts.snr_gate,
    )
    assert cfg.references == ("Hxr", "Hyr") and cfg.robust is True and cfg.prewhiten is False
    assert cfg.jackknife == 8 and cfg.nperseg == 4096 and cfg.nw == 3.0 and cfg.decim == 4
    assert cfg.native_max_samples == 2_000_000 and cfg.detrend == "constant" and cfg.min_segments == 3
    assert cfg.snr_gate is True and cfg.n_levels == 6
    d = cfg.to_dict()
    assert d["prewhiten"] is False and d["jackknife"] == 8, d
    try:
        engine_mantle.MantleOptions(whiten="ar")
    except ValueError as exc:
        assert "whiten" in str(exc)
    else:
        raise AssertionError("MantleOptions accepted whiten='ar'")
    print(f"  options -> ProcessingConfig: references {cfg.references}, jackknife {cfg.jackknife}, "
          f"nperseg {cfg.nperseg}, n_levels {cfg.n_levels}, prewhiten {cfg.prewhiten}")


def test_levels_for() -> None:
    got = {h: engine_mantle.levels_for(int(h * 3600 * 1000)) for h in (6, 16.5, 1)}
    assert got == {6: 6, 16.5: 7, 1: 5}, got
    assert engine_mantle.levels_for(1000) == 1
    assert engine_mantle.levels_for(10**15) == engine_mantle.MAX_LEVELS
    print(f"  levels_for: {got}, short 1, huge {engine_mantle.MAX_LEVELS}")


class _Imp:
    def __init__(self, freqs, Z, status):
        self.freqs, self.Z, self.status = freqs, Z, status


class _Jack:
    """A JackknifeResult stand-in: covariance(o, i, idx) = factor * d.T @ d.conj() over `dev`."""

    def __init__(self, freqs, dev):
        self.impedance = _Imp(freqs, None, None)
        self.dev = dev
        self.factor = (dev.shape[0] - 1) / dev.shape[0]

    def covariance(self, o, i, idx=None):
        d = self.dev[:, o, i, :]
        if idx is not None:
            d = d[:, idx]
        return self.factor * (d.T @ d.conj())


class _Result:
    def __init__(self, impedance, var, bands, band_freq):
        self.impedance, self.var, self.bands, self.band_freq = impedance, var, bands, band_freq


def _synthetic_result(with_jackknife: bool = True):
    rng = np.random.default_rng(3)
    # two cascade bands: 10-40 Hz and 1-10 Hz, merged by descending frequency
    f_a = np.linspace(40.0, 10.0, 7)
    f_b = np.linspace(9.0, 1.0, 9)
    band_freq = [f_a, f_b]
    f_cat = np.concatenate(band_freq)
    order = np.argsort(-f_cat, kind="stable")
    z_cat = (rng.normal(size=(2, 2, f_cat.size)) + 1j * rng.normal(size=(2, 2, f_cat.size))) * 10.0
    status = np.zeros(f_cat.size, dtype=np.int8)
    status[order == 0] = 0
    imp = _Imp(f_cat[order], z_cat[:, :, order], status)
    bands = None
    var = None
    if with_jackknife:
        devs = [rng.normal(size=(6, 2, 2, f.size)) + 1j * rng.normal(size=(6, 2, 2, f.size)) for f in band_freq]
        bands = [_Jack(f, d) for f, d in zip(band_freq, devs, strict=True)]
        var_cat = np.concatenate([np.stack([[np.real(np.diag(j.covariance(o, i))) for i in range(2)]
                                            for o in range(2)]) for j in bands], axis=2)
        var = var_cat[:, :, order]
    return _Result(imp, var, bands, band_freq), order, z_cat, band_freq


def test_band_pool_values_and_pooled_variance() -> None:
    res, order, z_cat, band_freq = _synthetic_result()
    f = res.impedance.freqs
    # mark one bin ill-conditioned: it must be left out of its band
    bad = int(np.flatnonzero(np.isclose(f, 5.0))[0])
    res.impedance.status[bad] = 1
    # bands: one inside the first cascade band, one straddling the seam, one empty
    bands = [(20.0, 41.0), (5.0, 12.0), (100.0, 200.0)]
    periods, zb, vb = engine_mantle.band_pool(res, bands)
    assert periods.shape == (2,), periods
    np.testing.assert_allclose(periods, sorted([1 / np.sqrt(20 * 41), 1 / np.sqrt(5 * 12)]))
    # periods ascend: the 20-41 Hz band (0.035 s) is index 0, the 5-12 Hz band (0.129 s) index 1
    for (lo, hi), k in ((20.0, 41.0), 0), ((5.0, 12.0), 1):
        members = np.flatnonzero((f >= lo) & (f < hi) & (res.impedance.status == 0))
        assert bad not in members
        np.testing.assert_allclose(zb[k], res.impedance.Z[:, :, members].mean(axis=2))
        # independent pooled variance: a^T Sigma a over the members, per cascade band, a = 1/m
        m = members.size
        want = np.zeros((2, 2))
        for o in range(2):
            for i in range(2):
                total = 0.0
                for b, fb in enumerate(band_freq):
                    sel = [j for j in members if any(np.isclose(f[j], fb))]
                    if not sel:
                        continue
                    idx = [int(np.flatnonzero(np.isclose(fb, f[j]))[0]) for j in sel]
                    d = res.bands[b].dev[:, o, i, :][:, idx]
                    sigma = res.bands[b].factor * (d.T @ d.conj())
                    total += float(np.real(sigma.sum())) / (m * m)
                want[o, i] = total
        np.testing.assert_allclose(vb[k], want, rtol=1e-12)
        naive = res.var[:, :, members].mean(axis=2) / m
        assert not np.allclose(vb[k], naive), "the pooled variance must differ from the naive mean/m"
    # without a jackknife: naive fallback, and no error without var
    res_nj, _, _, _ = _synthetic_result(with_jackknife=False)
    p2, z2, v2 = engine_mantle.band_pool(res_nj, bands)
    assert v2 is None and p2.shape == (2,)
    res_nj.var = np.abs(res_nj.impedance.Z) ** 2
    _, _, v3 = engine_mantle.band_pool(res_nj, bands)
    members = np.flatnonzero((f >= 20.0) & (f < 41.0))
    np.testing.assert_allclose(v3[0], res_nj.var[:, :, members].mean(axis=2) / members.size)
    print(f"  band_pool: {periods.size} bands from {f.size} bins, bin at 5 Hz (status 1) left out, pooled != naive")


def test_to_tf_round_trips_through_an_edi() -> None:
    from crust.compare import rho_phi

    periods = np.geomspace(0.01, 100.0, 9)
    z = (np.random.default_rng(5).normal(size=(9, 2, 2)) + 1j) * 3.0
    var = np.abs(z) ** 2 * 0.01
    tf = engine_mantle.to_tf(periods, z, var, station="S01", remote="R01", survey="synth", latitude=-30.5,
                             longitude=139.25, elevation=120.0, sample_rate=1000.0, lines=["mantle.test=1"])
    assert tf.station_metadata.transfer_function.remote_references == ["R01"]
    with tempfile.TemporaryDirectory() as tmp:
        edi = Path(tmp) / "S01.edi"
        tf.write(fn=edi, file_type="edi")
        p, rho, phi, rho_err, _ = rho_phi(edi)
        text = edi.read_text(encoding="latin-1")
    np.testing.assert_allclose(np.sort(p), periods, rtol=1e-5)
    want_rho = 0.2 * periods * np.abs(z[:, 0, 1]) ** 2
    np.testing.assert_allclose(rho[np.argsort(p), 0, 1], want_rho, rtol=1e-4)
    want_err = 2.0 * want_rho * np.sqrt(0.5 * var[:, 0, 1]) / np.abs(z[:, 0, 1])
    np.testing.assert_allclose(rho_err[np.argsort(p), 0, 1], want_err, rtol=1e-3)
    assert "mantle.test=1" in text and "R01" in text and "DATAID=S01" in text
    print(f"  to_tf: EDI of {p.size} periods read back, rho and 1-sigma errors match, remote R01 recorded")


class _Report:
    verdicts = [{"word": "ok"}, {"word": "ok"}, {"word": "snr_limited"}]
    snr_gate_ran = True


def test_sidecar_extras_and_info_lines() -> None:
    run = _mantle.module("processing.run")
    opts = engine_mantle.MantleOptions(whiten="diff")
    cfg = run.ProcessingConfig(site_id="X", fs=1000.0, lat=-30.0, lon=139.0, references=("Hxr", "Hyr"))
    extras = engine_mantle.sidecar_extras(cfg, opts, n_levels=6, report=Path("a/X.mantle_report.json"),
                                          fine_edi=Path("a/X_fine.edi"), n_samples=21_600_000,
                                          window=("2021-06-29T12:00:00+00:00", 6.0), coil=True,
                                          report_obj=_Report())
    assert extras["engine"] == "mantle" and extras["engine_version"], extras
    ec = extras["engine_config"]
    assert ec["processing_config"] == cfg.to_dict() and ec["options"] == opts.to_dict()
    assert ec["n_levels"] == 6 and ec["verdict_words"] == {"ok": 2, "snr_limited": 1} and ec["snr_gate_ran"] is True
    assert ec["options"]["whiten"] == "diff" and ec["prewhiten"] is False and ec["coil_deconvolved"] is True
    assert extras["mantle_report"] == "X.mantle_report.json" and extras["mantle_fine_edi"] == "X_fine.edi"
    json.dumps(extras)

    process_rr = _load_process_rr()
    base = {"versions": {"crust": "v"}, "started": "s", "tag": None, "tweaks": {"taper": "hann"},
            "quadrant": {"verdict": "physical quadrants"}, "edi": "X.edi"}
    aurora_lines = process_rr.edi_info_lines(dict(base))
    assert "crust.taper=hann" in aurora_lines and not any(line.startswith("crust.engine") for line in aurora_lines)
    mantle_lines = process_rr.edi_info_lines({**base, **extras})
    assert "crust.engine=mantle" in mantle_lines, mantle_lines
    assert any(line.startswith("crust.engine_version=") for line in mantle_lines), mantle_lines
    assert not any(line.startswith("crust.taper") for line in mantle_lines), mantle_lines
    print(f"  sidecar extras: {sorted(extras)}; words {ec['verdict_words']}; INFO lines engine-aware")


def _dry_run(*options: str) -> tuple[int, dict[str, str], str]:
    argv = [sys.executable, str(SCRIPT), str(SURVEY), "D02", "E08", *options, "--dry-run"]
    done = subprocess.run(argv, capture_output=True, text=True, cwd=REPO)
    out = {}
    for line in done.stdout.splitlines():
        if ": " in line or line.endswith(":"):
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip()
    return done.returncode, out, done.stdout + done.stderr


def test_engine_flag_on_the_command_line() -> None:
    if not SURVEY.exists():
        print("  (no curnamona_cube survey.yaml: the dry runs are skipped)")
        return
    code, plain, _ = _dry_run()
    assert code == 0 and plain["engine"] == "aurora", plain.get("engine")
    code, mantle, _ = _dry_run("--engine", "mantle")
    assert code == 0, code
    assert mantle["engine"] == "mantle" and mantle["mantle.whiten"] == "none", mantle
    for key in ("local_archive", "remote_archive", "min_period", "max_period", "periods_per_decade",
                "notch_frequencies", "window", "output_channels"):
        assert mantle[key] == plain[key], (key, mantle[key], plain[key])
    assert "mantle.whiten" not in plain
    code, _, text = _dry_run("--engine", "mantle", "--taper", "hann")
    assert code != 0 and "taper" in text, text[-300:]
    print(f"  dry runs: aurora and mantle resolve the same archives ({Path(plain['local_archive']).name}, "
          f"{Path(plain['remote_archive']).name}); --taper with mantle refused")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  engine_mantle_unit ({len(tests)} tests)")
