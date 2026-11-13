# -*- coding: utf-8 -*-
"""
Unit test for scripts/shared_centre_test.py (the shared-centre residual test)

Five synthetic EDL sites at 10 Hz are written as hourly ASCII files and
ingested with `ingest_site`, so their archives carry mt-io's real EDL chain
(the signed dipole stage, the x10 terminal box, the Bartington stages).
Each records 20 h, 14:00 to 10:00 UTC, two candidate UTC days of 10 h.
hx and hy are independent red-noise series (unit variance, x 2e4 words,
on a DC field); the lines are ex = 3e4 (hy + n_x), ey = 3e4 (-hx + n_y),
with independent noise n_x, n_y, in logger words:

- C: a common voltage 6e4 c(t) added to both lines (s = +1), noise 0.03;
  dipoles 48 / 44 m (unequal arms: the gain must still be 1 in samples);
- R: the common voltage added to ex and subtracted from ey (s = -1: one
  line with its centre on the plus terminal), declared layout 0 / 270;
- N: no common voltage, noise 0.3 (the control: the two lines incoherent);
- P: no common voltage, but a polarized field (hy = 0.99 hx + 0.14 h3), so
  the two lines are coherent (0.96) through the natural field alone,
  noise 0.1: the case where the lines' own coherence fools a test that
  does not remove the H-explained part;
- L: the common voltage of C on the second UTC day only (a centre that
  fails late, as at TAS112).

Usage:
    python tests/shared_centre_test_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - C does not read "holds" with residual coherence >= 0.98, |g| within
    1 +/- 0.03, s_obs +1, the clean diagonal "diff" both by the sign and
    by H, and the remedy applicable;
  - R does not read "holds" with |g| within 1 +/- 0.03, s_obs -1 and the
    clean diagonal "sum" both ways;
  - N does not read "control" (source coherence under 0.35 on its chosen
    days, the model not holding);
  - P does not read "fails" (source coherence 0.35 or more, the model not
    holding);
  - L with --days 1 does not choose its second day and read "holds", or
    reads a model-holds count other than 1 of 2;
  - the CLI run on all five (--days 1) does not write centre_test.csv with the five
    rows, the days and bands tables and one figure per site plus the
    summary, or its VERDICT lines do not say A FAIL at R (the one site
    whose sign differs from the prediction), B PASS with N as the control,
    and C applicable at C, R and L.

Mutation: with the H-explained part not removed (the cross-spectra of the
lines with hx and hy zeroed before `bin_stats`, so the residuals are the
lines themselves), P must read "holds": the test without its residual step
finds a shared centre where there is none, and the criterion on P catches
it.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import shared_centre_test as sct  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mt_workbench.ingest import default_archive_path, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "shared_centre_test.py"
SCRATCH = scratch_dir("shared_centre_test_unit")
FS = 10.0
T0 = pd.Timestamp("2016-02-01T14:00:00", tz="UTC")
HOURS = 20
N = int(HOURS * 3600 * FS)
SITES = {  # name: (common sign, noise, polarized, common on day 2 only, layout)
    "C": (+1, 0.03, False, False, {"dipole_length_ex": 48.0, "dipole_length_ey": 44.0}),
    "R": (-1, 0.03, False, False, {"azimuth_ey": 270.0}),
    "N": (0, 0.3, False, False, {}),
    "P": (0, 0.1, True, False, {}),
    "L": (+1, 0.03, False, True, {}),
}


def red(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return unit-variance red noise: integrated white noise high-passed at 5000 s."""
    x = np.cumsum(rng.standard_normal(n))
    sos = signal.butter(2, (1 / 5000.0) / (FS / 2), "high", output="sos")
    x = signal.sosfiltfilt(sos, x)
    return x / x.std()


def write_site(root: Path, name: str, seed: int) -> None:
    """Write one synthetic EDL site as hourly ASCII files of logger words."""
    sign, noise, polarized, late, _ = SITES[name]
    rng = np.random.default_rng(seed)
    hx = red(rng, N)
    hy = red(rng, N)
    if polarized:
        hy = 0.99 * hx + 0.14 * hy
    common = red(rng, N)
    if late:
        common[: int(10 * 3600 * FS)] = 0.0
    words = {
        "BX": 2.8e6 + 2e4 * hx, "BY": 1e3 + 2e4 * hy, "BZ": -3.3e6 + 50.0 * rng.standard_normal(N),
        "EX": 3e4 * (hy + noise * red(rng, N)) + (6e4 * common if sign else 0.0) + 5e3,
        "EY": 3e4 * (-hx + noise * red(rng, N)) + (sign * 6e4 * common if sign else 0.0) - 2e3,
    }
    site = root / "raw" / name
    shutil.rmtree(site, ignore_errors=True)
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{k}_samplerate=10\n" for k in range(5)), encoding="utf-8")
    per = int(3600 * FS)
    for h in range(HOURS):
        when = T0 + pd.Timedelta(hours=h)
        for suffix, values in words.items():
            np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}",
                       np.round(values[h * per:(h + 1) * per]).astype("int64"), fmt="%d")


def survey_yaml(root: Path) -> Path:
    """Write the survey.yaml of the five sites and return its path."""
    sites = {name: {"latitude": -41.0, "longitude": 146.0 + 0.01 * k, **SITES[name][4]}
             for k, name in enumerate(SITES)}
    config = {"name": "t", "instrument": "edl", "sample_rate": FS, "data_root": str(root / "raw"),
              "workspace": str(root / "work"),
              "defaults": {"dipole_length_ex": 50.0, "dipole_length_ey": 50.0, "azimuth_ex": 0.0, "azimuth_ey": 90.0,
                           "channels": ["ex", "ey", "hx", "hy", "hz"], "sensor_type": "bartington",
                           "flip_reversed_dipoles": True},
              "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    path = root / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def build(root: Path) -> Path:
    """Write and ingest the five sites; return the survey.yaml."""
    path = survey_yaml(root)
    sv = Survey.from_yaml(path)
    for k, name in enumerate(SITES):
        write_site(root, name, 100 + k)
        ingest_site(sv, name, out_path=default_archive_path(sv, name), overwrite=True)
    return path


def check(row: dict, verdict: str, s_obs: int | None = None, clean: str | None = None) -> list[str]:
    """Return what is wrong with a site's row against the expected verdict, sign and clean diagonal."""
    out = []
    if row["verdict"] != verdict:
        out.append(f"{row['site']} verdict {row['verdict']}, wanted {verdict}")
    if verdict == "holds":
        if not abs(row["resid_gain"] - 1.0) <= 0.03:
            out.append(f"{row['site']} |g| {row['resid_gain']:.3f}, wanted 1 +/- 0.03")
        if row["resid_coh"] < 0.98:
            out.append(f"{row['site']} residual coherence {row['resid_coh']:.3f} < 0.98")
    if s_obs is not None and row["s_obs"] != s_obs:
        out.append(f"{row['site']} s_obs {row['s_obs']:+d}, wanted {s_obs:+d}")
    if clean is not None and (row["clean_obs"] != clean or row["clean_by_H"] != clean or not row["remedy_applicable"]):
        out.append(f"{row['site']} clean {row['clean_obs']} / by H {row['clean_by_H']} / remedy "
                   f"{row['remedy_applicable']}, wanted {clean} both ways and the remedy applicable")
    if verdict == "control" and (row["src_max"] >= sct.CONTROL_COH or row["model_holds"]):
        out.append(f"{row['site']} source coherence max {row['src_max']:.2f} or the model holds")
    if verdict == "fails" and row["src_max"] < sct.CONTROL_COH:
        out.append(f"{row['site']} source coherence max {row['src_max']:.2f} under {sct.CONTROL_COH}")
    return out


def test_sites(path: Path) -> None:
    """The five sites through `run_site`, and the mutation."""
    band = (10.0, 1000.0)
    problems, rows = [], {}
    for name, verdict, s_obs, clean in (("C", "holds", 1, "diff"), ("R", "holds", -1, "sum"),
                                        ("N", "control", None, None), ("P", "fails", None, None)):
        rows[name] = sct.run_site(str(path), name, 2, band)["row"]
        problems += check(rows[name], verdict, s_obs, clean)
        r = rows[name]
        print(f"  {name}: {r['verdict']}, residual coherence {r['resid_coh']:.3f}, |g| {r['resid_gain']:.3f}, arg "
              f"{r['arg_g']:+.1f} deg, s_obs {r['s_obs']:+d}, src max {r['src_max']:.2f}, H coherence diff "
              f"{r['mcoh_diff']:.2f} sum {r['mcoh_sum']:.2f}")
    late = sct.run_site(str(path), "L", 1, band)
    r = late["row"]
    problems += check(r, "holds", 1, "diff")
    if r["days"] != "2016-02-02" or r["days_model"] != 1 or r["days_usable"] != 2:
        problems.append(f"L chose {r['days']!r}, model days {r['days_model']} of {r['days_usable']}: wanted "
                        f"2016-02-02 and 1 of 2")
    print(f"  L (--days 1): chose {r['days']}, {r['verdict']}, model days {r['days_model']} of {r['days_usable']}")
    assert not problems, problems

    real = sct.bin_stats

    def no_h_removal(f, spectra, band):
        """The mutation: the lines' cross-spectra with hx and hy zeroed, so the H-explained part stays."""
        cut = dict(spectra)
        for e in ("ex", "ey"):
            for h in ("hx", "hy"):
                cut[(e, h)] = np.zeros_like(spectra[(e, h)])
                cut[(h, e)] = np.zeros_like(spectra[(h, e)])
        return real(f, cut, band)

    sct.bin_stats = no_h_removal
    try:
        mutant = sct.run_site(str(path), "P", 2, band)["row"]
    finally:
        sct.bin_stats = real
    assert mutant["verdict"] == "holds", mutant
    print(f"  mutation (H part not removed): P reads {mutant['verdict']} (residual coherence "
          f"{mutant['resid_coh']:.2f}, |g| {mutant['resid_gain']:.2f}): caught by P's criterion")


def test_cli(path: Path) -> None:
    """The script on all five sites: the tables, the figures and the VERDICT lines."""
    out = path.parent / "qc"
    shutil.rmtree(out, ignore_errors=True)
    run = subprocess.run([sys.executable, str(SCRIPT), str(path), *SITES, "--days", "1", "--out", str(out)],
                         capture_output=True, text=True, timeout=1800)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text[-3000:]
    table = pd.read_csv(out / "centre_test.csv")
    assert sorted(table["site"]) == sorted(SITES), table["site"].tolist()
    for name in ("centre_test_days.csv", "centre_test_bands.csv", "centre_test_summary.png",
                 *[f"{s}_centre_test.png" for s in SITES]):
        assert (out / name).exists(), name
    lines = [line for line in text.splitlines() if line.startswith("VERDICT")]
    assert any(" A " in line and "FAIL at R" in line for line in lines), lines
    assert any(" B " in line and "1 control sites" in line and "PASS" in line for line in lines), lines
    c_line = next(line for line in lines if " C " in line)
    applies = c_line.split(":", 1)[1].split(";")[0].split()
    assert sorted(applies) == ["C", "L", "R"], c_line
    for line in lines:
        print("  " + line)


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    root = SCRATCH / "survey"
    survey_path = build(root)
    test_sites(survey_path)
    print("  ok  test_sites")
    test_cli(survey_path)
    print("  ok  test_cli")
    print("\nPASS  shared_centre_test_unit (2 tests)")
