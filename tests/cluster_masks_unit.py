# -*- coding: utf-8 -*-
"""
Unit test for scripts/cluster_masks.py

Checks the clustering of one band's chunk impedances, the masks built from
it, their replacement in masks.yaml and the usable-band rule, on synthetic
arrays and a temporary survey folder. Runs without an archive.

A band's groups are drawn in the plane the script clusters: Zyx with the
phase of -Zyx at the drawn phase (the yx plus 180 deg convention), log10 |Z|
and phase with Gaussian scatter, coherence 0.9 for the clusters and 0.2
for a set of noise groups at uniform random phase and |Z| (the coherence
gate drops them). Groups sit on a 600 s grid from T0 in a random order of
the two clusters, so runs of consecutive source groups occur.

Usage:
    python tests/cluster_masks_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (a) two well-separated clusters, 60 Earth groups at 45 +/- 4 deg and
   log10 |Z| 2.0 +/- 0.05 and 60 source groups at 2 +/- 3 deg and log10 |Z|
   2.5 +/- 0.05, with 12 noise groups, do not give an accepted split with
   at least 90 % of the source groups masked and at most 5 % of the Earth
   groups, and none of the noise groups; the same holds for Zxy drawn at
   the phase itself, and when the Earth holds 20 % of 120 groups;
2. (b) one cluster (120 groups at 45 +/- 4 deg, log10 |Z| 2.0 +/- 0.05, with
   the noise groups) gives any mask; or a band the source holds alone (100
   groups at 1.5 +/- 3 deg, log10 |Z| 2.7) with a coherent group of 15
   outliers at -45 +/- 10 deg gives any mask (the cluster farther from
   0 deg lies outside 0-90 deg, so no cluster is the Earth's; taking the
   cluster nearer 45 deg as the Earth masks the outliers and fails this);
   or a band whose second cluster lies far from 0 deg (Earth 70 +/- 8 deg,
   a coherent cluster at -50 +/- 12 deg, 60 groups each) gives any mask or
   a verdict that does not name the source-phase rule;
3. (c) two clusters whose median phases differ by 10 deg (25 and 15 deg,
   log10 |Z| 2.0 and 2.5) give any mask, or their verdict does not name the
   separation rule;
4. (d) the masks of a band are not one per run of consecutive masked groups
   over the run's span (groups 1-3 and 5 of 7 masked give exactly two masks,
   [start 1, end 3] and [start 5, end 5]), any record fails
   `crust.masks.normalise` or differs from its normalised form, found_by is
   not "cluster", bands is not the band's [pmin, pmax], the reason does not
   carry the component, both phases, the separation and the chunk count,
   or `crust.masks.applies` takes the mask for a neighbouring band's centre;
   or --dilate 1 (`dilate`) on groups 1 and 5 of 10 does not mask groups
   0-2 and 4-6 (one either side, none past the band's first group), or
   merges them other than into two masks whose reason says "dilated by
   1 group(s)"; --dilate 2 on the same groups must give one mask over
   groups 0-7;
5. (e) the --write path (`write_site_masks`) on a temporary survey does not
   keep the site's time and polar masks equal to what they were, remove
   its earlier cluster masks, add the new ones, and leave another site's
   block and the file's header unchanged in the text; a second write with
   no masks does not leave only the time and polar masks;
6. the usable-band rule (`usable_bands`, `longest_run`) does not take a
   flat-rho band at 40 deg as usable, or takes as usable a band whose rho
   rises as the period (slope 1) with a phase of 35 deg (the rho slope
   calls for about 0 deg) or one at 2 deg, or one of a smooth near-field
   onset whose rho rises as T^0.7 at 15 deg (consistent with the slope, but
   steeper than 0.5); on a curve usable from band 0 to band 11 and then
   contaminated, the longest run is not bands 0-11;
7. a mutated rule passes: with the Earth cluster taken as the one nearer
   0 deg (`earth_index` swapped), criterion 1 must fail, and with
   --min-separation 5 criterion 3 must fail; the test runs both mutations
   and fails if either criterion still holds.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import cluster_masks as cm  # noqa: E402
from crust.masks import HEADER, applies, load_masks, masks_path, normalise, save_masks  # noqa: E402

T0 = pd.Timestamp("2023-07-22T00:00:00", tz="UTC")
CHUNK_S = 600.0
N_NOISE = 12


def band(clusters, seed: int = 3, component: str = "yx", noise: int = N_NOISE):
    """Draw one band's groups.

    Args:
        clusters: [(n, phase deg, phase sd, log10 |Z|, log10 |Z| sd)], one entry per cluster.
        seed (int): The random generator's seed.
        component (str): "yx" draws Z at the phase of -Z, "xy" at the phase of Z.
        noise (int): Noise groups at uniform phase and |Z|, coherence 0.2.

    Returns:
        dict: ``z``, ``coherence``, ``n_windows``, ``starts``, ``ends`` and
        ``label`` (the cluster index per group, -1 for noise), in a random order.
    """
    rng = np.random.default_rng(seed)
    phase, logz, label = [], [], []
    for k, (n, ph, ph_sd, lz, lz_sd) in enumerate(clusters):
        phase.append(ph + ph_sd * rng.standard_normal(n))
        logz.append(lz + lz_sd * rng.standard_normal(n))
        label.append(np.full(n, k))
    phase.append(rng.uniform(-180.0, 180.0, noise))
    logz.append(rng.uniform(1.0, 3.0, noise))
    label.append(np.full(noise, -1))
    phase, logz, label = np.concatenate(phase), np.concatenate(logz), np.concatenate(label)
    order = rng.permutation(label.size)
    phase, logz, label = phase[order], logz[order], label[order]
    z = 10**logz * np.exp(1j * np.radians(phase))
    if component == "yx":
        z = -z
    coherence = np.where(label >= 0, 0.9, 0.2)
    n = label.size
    starts = T0 + pd.to_timedelta(np.arange(n) * CHUNK_S, unit="s")
    return {"z": z, "coherence": coherence, "n_windows": np.full(n, 900), "starts": starts,
            "ends": starts + pd.Timedelta(seconds=CHUNK_S), "label": label}


def two_clusters(component: str = "yx", n_earth: int = 60, n_source: int = 60, seed: int = 3):
    """Criterion 1's band: an Earth cluster at 45 deg and a source cluster at 2 deg with larger |Z|."""
    return band([(n_earth, 45.0, 4.0, 2.0, 0.05), (n_source, 2.0, 3.0, 2.5, 0.05)], seed, component)


def check_a(b, res) -> tuple[float, float]:
    """Criterion 1: the split is accepted, >= 90 % of the source masked, <= 5 % of the Earth, no noise group."""
    masked = res["masked"]
    source, earth = masked[b["label"] == 1].mean(), masked[b["label"] == 0].mean()
    assert res["accepted"], res["verdict"]
    assert source >= 0.9, f"{source:.2f} of the source groups masked"
    assert earth <= 0.05, f"{earth:.2f} of the Earth groups masked"
    assert not masked[b["label"] < 0].any(), "a noise group masked"
    return source, earth


def check_c(res) -> None:
    """Criterion 3: no mask, the verdict naming the separation rule."""
    assert not res["masked"].any(), f"{res['masked'].sum()} group(s) masked"
    assert "separation" in res["verdict"], res["verdict"]


def c_band():
    """Criterion 3's band: two clusters 10 deg apart."""
    return band([(60, 25.0, 3.0, 2.0, 0.05), (60, 15.0, 3.0, 2.5, 0.05)], seed=5)


def test_a_two_clusters() -> None:
    for component in ("yx", "xy"):
        b = two_clusters(component)
        res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], component)
        source, earth = check_a(b, res)
        print(f"  (a) {component}: accepted ({res['verdict']}), Earth {res['earth_phase']:.1f} deg, source "
              f"{res['source_phase']:.1f} deg, separation {res['separation']:.1f}; {source:.0%} of the source and "
              f"{earth:.0%} of the Earth groups masked, no noise group")
    b = two_clusters(n_earth=24, n_source=96, seed=7)
    res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], "yx")
    source, earth = check_a(b, res)
    print(f"  (a) Earth 20 % of 120: Earth fraction {res['earth_fraction']:.2f}, {source:.0%} of the source and "
          f"{earth:.0%} of the Earth groups masked")


def test_b_one_cluster() -> None:
    b = band([(120, 45.0, 4.0, 2.0, 0.05)], seed=11)
    res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], "yx")
    assert not res["masked"].any(), (res["verdict"], res["masked"].sum())
    print(f"  (b) one cluster: no mask ({res['verdict']})")
    b = band([(100, 1.5, 3.0, 2.7, 0.05), (15, -45.0, 10.0, 2.5, 0.1)], seed=13)
    res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], "yx")
    assert not res["masked"].any(), (res["verdict"], res["masked"].sum())
    assert "physical phase" in res["verdict"], res["verdict"]
    print(f"  (b) the source alone with coherent outliers at -45 deg: no mask ({res['verdict']})")
    b = band([(60, 70.0, 8.0, 1.5, 0.1), (60, -50.0, 12.0, 1.4, 0.1)], seed=17)
    res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], "yx")
    assert not res["masked"].any(), (res["verdict"], res["masked"].sum())
    assert "source cluster phase" in res["verdict"], res["verdict"]
    print(f"  (b) a second cluster at -50 deg: no mask ({res['verdict']})")


def test_c_close_clusters() -> None:
    res = cm.cluster_band(*(c_band()[k] for k in ("z", "coherence", "n_windows")), "yx")
    check_c(res)
    print(f"  (c) clusters 10 deg apart: no mask ({res['verdict']})")


def test_d_records() -> None:
    n = 7
    starts = T0 + pd.to_timedelta(np.arange(n) * CHUNK_S, unit="s")
    ends = starts + pd.Timedelta(seconds=CHUNK_S)
    masked = np.array([False, True, True, True, False, True, False])
    lo, hi = 1.0 / 0.2263 / 10 ** 0.05, 1.0 / 0.2263 * 10 ** 0.05  # a 10-per-decade band centred on 0.2263 s
    pmin, pmax = 1.0 / hi, 1.0 / lo
    split = {"source_phase": 1.8, "source_z": 263.4, "earth_phase": 36.1, "separation": 34.3, "n_source": 4,
             "n": 7}
    recs = cm.mask_records(starts, ends, masked, pmin, pmax, "yx", split)
    assert len(recs) == 2, recs
    assert (recs[0]["start"], recs[0]["end"]) == (normalise({"start": starts[1], "end": ends[3]})["start"],
                                                  normalise({"start": starts[1], "end": ends[3]})["end"]), recs[0]
    assert (pd.Timestamp(recs[1]["start"]), pd.Timestamp(recs[1]["end"])) == (starts[5], ends[5]), recs[1]
    for r in recs:
        assert normalise(r) == r, r
        assert r["found_by"] == "cluster" and r["bands"] == [pmin, pmax], r
        for text in ("cluster mask: yx source cluster phase 1.8 deg", "|Z| 263", "Earth cluster phase 36.1 deg",
                     "separation 34.3 deg", "4/7 chunks"):
            assert text in r["reason"], (text, r["reason"])
        centre = 1.0 / np.sqrt(lo * hi)
        assert applies(r, centre), r
        assert not applies(r, centre * 10**0.1) and not applies(r, centre / 10**0.1), r
    print(f"  (d) groups 1-3 and 5 of 7 -> two masks, {recs[0]['start']} to {recs[0]['end']} and {recs[1]['start']} "
          f"to {recs[1]['end']}; normalised, found_by cluster, bands [{pmin:.4g}, {pmax:.4g}], neighbours untouched")
    print(f"      reason: {recs[0]['reason']}")
    n = 10
    starts = T0 + pd.to_timedelta(np.arange(n) * CHUNK_S, unit="s")
    ends = starts + pd.Timedelta(seconds=CHUNK_S)
    source = np.zeros(n, bool)
    source[[1, 5]] = True
    grown = cm.dilate(source, 1)
    assert np.flatnonzero(grown).tolist() == [0, 1, 2, 4, 5, 6], grown
    recs = cm.mask_records(starts, ends, grown, pmin, pmax, "yx", split, dilated=1)
    assert [(pd.Timestamp(r["start"]), pd.Timestamp(r["end"])) for r in recs] == [(starts[0], ends[2]),
                                                                                  (starts[4], ends[6])], recs
    assert all("dilated by 1 group(s)" in r["reason"] for r in recs), recs[0]["reason"]
    recs2 = cm.mask_records(starts, ends, cm.dilate(source, 2), pmin, pmax, "yx", split, dilated=2)
    assert [(pd.Timestamp(r["start"]), pd.Timestamp(r["end"])) for r in recs2] == [(starts[0], ends[7])], recs2
    assert np.array_equal(cm.dilate(source, 0), source)
    print("  (d) --dilate 1 on groups 1 and 5 of 10 -> groups 0-2 and 4-6, two masks; --dilate 2 -> one mask 0-7")


def test_e_write() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        time_mask = {"start": T0, "end": T0 + pd.Timedelta(hours=1), "bands": "all", "reason": "hour",
                     "found_by": "time"}
        polar = {"start": T0 + pd.Timedelta(hours=2), "end": T0 + pd.Timedelta(hours=2, minutes=10),
                 "bands": [0.2, 0.25], "reason": "polar yx panel", "found_by": "polar"}
        old = {"start": T0 + pd.Timedelta(hours=3), "end": T0 + pd.Timedelta(hours=4), "bands": [0.3, 0.4],
               "reason": "cluster mask: old", "found_by": "cluster"}
        other_site = [{**polar, "reason": "Y's own"}]
        save_masks(survey_yaml, "X", [time_mask, polar, old])
        save_masks(survey_yaml, "Y", other_site)
        before = masks_path(survey_yaml).read_text(encoding="utf-8")
        y_block = before[before.index("Y:"):]
        keep_before = [m for m in load_masks(survey_yaml, "X") if m["found_by"] != "cluster"]
        new = [normalise({"start": T0 + pd.Timedelta(hours=5), "end": T0 + pd.Timedelta(hours=5, minutes=20),
                          "bands": [0.2, 0.25], "reason": "cluster mask: new", "found_by": "cluster"}),
               normalise({"start": T0 + pd.Timedelta(hours=6), "end": T0 + pd.Timedelta(hours=6, minutes=10),
                          "bands": [1.0, 1.25], "reason": "cluster mask: new", "found_by": "cluster"})]
        kept, removed, written = cm.write_site_masks(survey_yaml, "X", new)
        after = load_masks(survey_yaml, "X")
        text = masks_path(survey_yaml).read_text(encoding="utf-8")
        assert (kept, removed, written) == (2, 1, 2), (kept, removed, written)
        assert [m for m in after if m["found_by"] != "cluster"] == keep_before, after
        cluster = [m for m in after if m["found_by"] == "cluster"]
        assert cluster == new, cluster
        assert "cluster mask: old" not in text, text
        assert text.startswith(HEADER) and text.endswith(y_block) and y_block.startswith("Y:"), text
        kept2, removed2, written2 = cm.write_site_masks(survey_yaml, "X", [])
        assert (kept2, removed2, written2) == (2, 2, 0) and load_masks(survey_yaml, "X") == keep_before
        out = cm.write_mask_file(Path(tmp) / "out" / "x.yaml", "X", new)
        assert out.read_text(encoding="utf-8").startswith(HEADER), out
        assert cm.yaml.safe_load(out.read_text(encoding="utf-8")) == {"X": new}
    print("  (e) --write: the time and polar masks kept equal, the earlier cluster mask replaced by the two new "
          "ones, Y's block and the header unchanged; an empty write leaves the time and polar masks; --out's "
          "file holds the site's block")


def test_f_usable() -> None:
    periods = 0.01 * 10 ** (0.1 * np.arange(20))
    rho = np.full(20, 100.0)
    phase = np.full(20, 40.0)
    rho[12:] = 100.0 * periods[12:] / periods[11]  # slope 1 from band 12 on
    phase[12:] = 35.0
    err = np.full(20, 1.0)
    good = cm.usable_bands(periods, rho, phase, err)
    assert good[:12].all(), good
    assert not good[14:].any(), good
    assert cm.longest_run(good) == (0, 11), cm.longest_run(good)
    phase[12:] = 2.0
    assert not cm.usable_bands(periods, rho, phase, err)[12:].any()
    rho[12:] = 100.0 * (periods[12:] / periods[11]) ** 0.7
    phase[12:] = 15.0
    assert not cm.usable_bands(periods, rho, phase, err)[14:].any()
    print(f"  (f) flat rho at 40 deg usable, rho rising as T at 35 deg or 2 deg, or as T^0.7 at 15 deg, not; longest run bands "
          f"{cm.longest_run(good)} ({periods[0]:.3g}-{periods[11]:.3g} s)")


def test_g_mutations() -> None:
    b = two_clusters()
    saved = cm.earth_index
    cm.earth_index = lambda medians: int(np.argmin(np.abs(np.asarray(medians, float))))
    try:
        res = cm.cluster_band(b["z"], b["coherence"], b["n_windows"], "yx")
        try:
            check_a(b, res)
        except AssertionError as exc:
            print(f"  (g) Earth taken as the cluster nearer 0 deg: criterion 1 trips ({exc})")
        else:
            raise AssertionError("criterion 1 held with the Earth and source clusters swapped")
    finally:
        cm.earth_index = saved
    cb = c_band()
    res = cm.cluster_band(cb["z"], cb["coherence"], cb["n_windows"], "yx", min_separation=5.0)
    try:
        check_c(res)
    except AssertionError as exc:
        print(f"  (g) --min-separation 5: criterion 3 trips ({exc})")
    else:
        raise AssertionError("criterion 3 held with the separation rule at 5 deg")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  cluster_masks_unit ({len(tests)} tests)")
