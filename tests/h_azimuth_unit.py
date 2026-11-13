# -*- coding: utf-8 -*-
"""
Unit test for scripts/h_azimuth.py: the fluxgate field table, the rotation fit and the in-place `rot_h` write

The field table's azimuth is read on the Tasmania AusLAMP 2016 pilot
archives TAS100 and TAS107 (the survey workspace's `mth5`, built on the
sensor axes, or turned by their
declared `rot_h` since: `azimuth_sensor` is the same either way) and on the
synthetic EDL site of tests/ingest_rot_h_unit.py (a main field at +30 deg in
the sensor frame), ingested without and with `rot_h: 30.0`. The rotation fit
is run on a synthetic tensor k R(phi), and the survey.yaml write on a
synthetic survey.yaml with comments.

Usage:
    python tests/h_azimuth_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - H1: `field_row` reads TAS100's `azimuth_sensor` outside -21.6 +/- 0.2
    deg or TAS107's outside +157.6 +/- 0.2 deg (the values measured on
    those archives), or either F / IGRF outside 0.98-1.02 (skipped,
    with a line saying so, when the workspace is not on this machine);
  - H2: on the synthetic site `azimuth_sensor` is not 30.00 +/- 0.01 deg
    without the key, or with `rot_h: 30.0` `azimuth` is not 0.00 +/- 0.01,
    `rot_h_recorded` not 30.0 and `azimuth_sensor` not 30.00 +/- 0.01;
  - H3: `rotation_fit` of k R(phi) (k 0.8, phi +30 and -150 deg, any error
    weights) is off by more than 1e-9 in phi or k; or `neighbour_columns`
    of a base at +10 deg and a local at -20 deg with M = R(30 deg) does not
    give `azimuth_neighbour` -20 and difference 0, or with M = R(37 deg)
    does not flag (difference -7) and with R(45 deg) does not hold;
  - H4: `apply_rot_h` on a survey.yaml with comments changes anything but
    the named sites' `rot_h` lines (one added, one replaced), changes the
    comment count, or writes no copy; or it writes anything when the new
    value is refused by `Survey.site` (rot_h 200) or the edit would
    change another key (the mutation: `set_rot_h` replaced by one that
    also rewrites a latitude), the file then unchanged.
"""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

from mt_workbench.ingest import ingest_site  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
import ingest_rot_h_unit as rh  # noqa: E402

spec = importlib.util.spec_from_file_location("h_azimuth", REPO / "scripts" / "h_azimuth.py")
ha = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ha)

SCRATCH = scratch_dir("h_azimuth_unit")
TAS_YAML = REPO / "surveys" / "tasmania_auslamp_2016" / "survey.yaml"
PILOT = {"TAS100": -21.6, "TAS107": 157.6}


def test_pilot() -> None:
    """H1: the pilot's two sites read their B2 azimuths."""
    import yaml as _yaml

    ws = Path(_yaml.safe_load(TAS_YAML.read_text(encoding="utf-8"))["workspace"])
    if not all((ws / "mth5" / f"{s}.h5").exists() for s in PILOT):
        print(f"  H1 skipped: no pilot archives under {ws / 'mth5'}")
        return
    for site, want in PILOT.items():
        row = ha.field_row(str(TAS_YAML), site)
        assert abs(ha.wrap(row["azimuth_sensor"] - want)) <= 0.2, (site, row["azimuth_sensor"], want)
        assert 0.98 <= row["F_ratio"] <= 1.02, (site, row["F_ratio"])
        print(f"  H1 {site}: azimuth_sensor {row['azimuth_sensor']:+.2f} (pilot {want:+.1f}; archive "
              f"{row['azimuth']:+.2f}, rot_h recorded {row['rot_h_recorded']:g}), tilt {row['tilt_deg']:+.2f}, "
              f"F/IGRF {row['F_ratio']:.3f}, |hz|/IGRF {row['hz_ratio']:.3f}, |H|/IGRF {row['H_ratio']:.3f}")


def synthetic_yaml(root: Path, own: dict) -> Path:
    """Write the survey.yaml of the synthetic EDL site of tests/ingest_rot_h_unit.py with a position."""
    entry = {"latitude": -41.0, "longitude": 145.0, "elevation": 100.0, "start": "2009-03-20T00:00:00Z",
             "end": "2009-03-20T00:10:00Z", **own}
    config = {"name": "t", "instrument": "edl", "sample_rate": 10, "data_root": str(root / "raw"),
              "workspace": str(root / "work"),
              "defaults": {"dipole_length_ex": 49.0, "dipole_length_ey": 51.0,
                           "channels": ["ex", "ey", "hx", "hy", "hz"]},
              "sites": {rh.SITE: entry}}
    path = root / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def test_synthetic() -> None:
    """H2: the synthetic +30 deg field, without and with rot_h 30.0."""
    root = SCRATCH / "synthetic"
    rh.write_site(root, 30.0)
    from mt_workbench.survey import Survey

    for own, want_az in (({}, 30.0), ({"rot_h": 30.0}, 0.0)):
        path = synthetic_yaml(root, own)
        ingest_site(Survey.from_yaml(path), rh.SITE, overwrite=True)
        row = ha.field_row(str(path), rh.SITE)
        assert abs(row["azimuth"] - want_az) <= 0.01, (own, row["azimuth"])
        assert abs(row["azimuth_sensor"] - 30.0) <= 0.01, (own, row["azimuth_sensor"])
        assert row["rot_h_recorded"] == own.get("rot_h", 0.0), (own, row["rot_h_recorded"])
        print(f"  H2 {own or 'no key'}: azimuth {row['azimuth']:+.4f}, rot_h_recorded {row['rot_h_recorded']:g}, "
              f"azimuth_sensor {row['azimuth_sensor']:+.4f}, proposed rot_h {row['rot_h_proposed']:.2f}")


def tensor_frame(k: float, phi: float, periods=(10.0, 30.0, 100.0, 300.0, 1000.0), seed: int = 1) -> pd.DataFrame:
    """Return process_intersite-style csv rows of M = k R(phi) with random error columns."""
    rng = np.random.default_rng(seed)
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    m = {"xx": k * c, "xy": k * s, "yx": -k * s, "yy": k * c}
    rows = []
    for p in periods:
        row = {"period": p}
        for ij, v in m.items():
            row.update({f"M_{ij}_re": v, f"M_{ij}_im": 0.0, f"M_{ij}_err": float(rng.uniform(0.01, 0.2))})
        rows.append(row)
    return pd.DataFrame(rows)


def test_rotation() -> None:
    """H3: the per-period fit and the neighbour columns' signs."""
    for phi in (30.0, -150.0):
        fit = ha.rotation_fit(tensor_frame(0.8, phi))
        assert np.allclose(fit.phi, phi, atol=1e-9) and np.allclose(fit.k, 0.8, atol=1e-9), (phi, fit)
    print("  H3 rotation_fit of 0.8 R(+30) and 0.8 R(-150): phi and k to 1e-9")
    root = SCRATCH / "neighbour"
    root.mkdir(parents=True, exist_ok=True)
    got = {}
    for phi in (30.0, 37.0, 45.0):
        frame = tensor_frame(1.0, phi)
        path = root / f"M_{phi:g}.csv"
        frame.to_csv(path, index=False)
        path.with_suffix(".json").write_text(json.dumps({"timing_check": {"tau_ms": 1.0, "tau_err_ms": 2.0}}),
                                             encoding="utf-8")
        got[phi] = ha.neighbour_columns(path, local_az=-20.0, base_az=10.0)
    a = got[30.0]
    assert abs(a["azimuth_neighbour"] + 20.0) < 1e-9 and abs(a["difference"]) < 1e-9 and not a["flag"], a
    assert got[37.0]["flag"] and not got[37.0]["hold"] and abs(got[37.0]["difference"] + 7.0) < 1e-9, got[37.0]
    assert got[45.0]["hold"], got[45.0]
    print(f"  H3 base +10, local -20: M = R(30) gives azimuth_neighbour {a['azimuth_neighbour']:+.1f}, difference "
          f"{a['difference']:+.1f}; R(37) flags ({got[37.0]['difference']:+.1f}), R(45) holds "
          f"({got[45.0]['difference']:+.1f})")


SURVEY_TEXT = """name: t
instrument: edl
sample_rate: 10
data_root: {root}
# a comment at the top
defaults:
  dipole_length_ex: 50.0  # an inline comment
sites:
  A01:
    latitude: -41.0
    longitude: 145.0
    # a comment inside an entry
    notes: 'phase 1'
  A02:
    latitude: -41.1
    longitude: 145.1
    rot_h: 12.5
  A03:
    latitude: -41.2
    longitude: 145.2
# a comment after the sites
"""


def test_apply() -> None:
    """H4: the in-place write, its copy and its refusals."""
    root = SCRATCH / "apply"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    path = root / "survey.yaml"
    path.write_text(SURVEY_TEXT.format(root=root.as_posix()), encoding="utf-8", newline="\n")
    before = path.read_bytes()
    copy = ha.apply_rot_h(path, {"A01": -21.55, "A02": 157.6})
    after = path.read_text(encoding="utf-8")
    assert copy.exists() and copy.read_bytes() == before, copy
    old_lines, new_lines = before.decode().splitlines(), after.splitlines()
    added = [ln for ln in new_lines if ln not in old_lines]
    removed = [ln for ln in old_lines if ln not in new_lines]
    assert added == ["    rot_h: -21.55", "    rot_h: 157.60"] and removed == ["    rot_h: 12.5"], (added, removed)
    assert ha.comment_count(after) == ha.comment_count(before.decode()) == 4
    parsed = yaml.safe_load(after)
    assert parsed["sites"]["A01"]["rot_h"] == -21.55 and parsed["sites"]["A02"]["rot_h"] == 157.6
    assert "rot_h" not in parsed["sites"]["A03"]
    print(f"  H4 apply: lines added {added}, removed {removed}; comments 4 -> 4; copy {copy.name}")
    state = path.read_bytes()
    for what, values, patch in (("rot_h 200", {"A03": 200.0}, None),
                                ("a latitude rewritten too", {"A03": 5.0}, "mutant")):
        real = ha.set_rot_h
        if patch:
            ha.set_rot_h = lambda text, values: real(text, values).replace("latitude: -41.2", "latitude: -41.3")
        try:
            ha.apply_rot_h(path, values)
        except ValueError as exc:
            assert path.read_bytes() == state, what
            print(f"  H4 {what}: refused, the file as it was ({str(exc)[:90]}...)")
        else:
            raise AssertionError(f"{what}: written")
        finally:
            ha.set_rot_h = real


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1])
    tests = [test_rotation, test_apply, test_synthetic, test_pilot]
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  h_azimuth_unit ({len(tests)} tests)")
