# -*- coding: utf-8 -*-
"""
Unit test for the LEMI-424 ingest: stored names, E sign convention, metadata

Part 1 writes a synthetic LEMI-424 day file of five lines (the 24-field
layout of mt-io's reader, the numbers chosen here) into a scratch data
root, describes it in a survey.yaml written as text, and ingests it with
`mt_workbench.ingest.ingest_site`. The archive is read back with mth5 and
its samples compared with the file's own columns read here with numpy.
Part 2 ingests one real hour of a LEMI-424, MBJ21 (WA-MT 2024, cut by
`tests/instrument_samples.py`), the same way. Part 3 checks the channel
presets.

Usage:
    python tests/lemi424_ingest_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) with `e_sign: -1.0` and `channels` "E1 E2 Bx By Bz": the archive's run
    does not hold exactly ex ey hx hy hz; ex and ey are not the file's E1
    and E2 columns unchanged (the logger's words), or hx hy hz not its Bx
    By Bz columns, sample for sample; ex's or ey's chain is not the one
    stage `lemi424_e_sign`, a coefficient filter of gain -1 with mV/km in
    and out recorded as applied (as `h_scale` is), or hx's chain is not
    empty; the stages the products remove
    (`aurora.time_series.spectrogram_helpers.get_calibration_filters`,
    which `calibrate_stft_obj` calls for every channel of every product)
    are not [lemi424_e_sign] for ex with response -1 at 0.01 Hz, so that
    the products read -E1; `mt_workbench.timefreq._scalar_gain` of ex (the
    GUI's time series and the site QC figures) is not -1 times its value
    without the stage (+1, the archive of (2)), or ex as `timefreq` scales
    it (samples / gain) is not minus the file's E1; the run comment does not
    carry the sentence "LEMI-424 E sign convention e_sign -1 recorded in the
    chain of ex, ey (E1, E2 are recorded with the opposite sign to the
    x-north, y-east frame), the samples are the logger's columns"; ex and ey
    `dipole_length` are not the survey's 88 and 100 m; the
    `measurement_azimuth` of hx hy hz ex ey is not 0 90 0 0 90, or the
    `measurement_tilt` of hz not 90 and of the others not 0 (as the EDL
    reader writes them); or e3, e4 or a temperature channel is named in the
    run's channel list or in the station's channels_recorded;
(2) after the one-line change `e_sign: -1.0` -> `e_sign: 1.0`, ex and ey are
    not the E1 and E2 columns unchanged, their chains not empty, their
    scalar gain not +1, the products' response not 1 with nothing removed,
    or the run comment still carries the e_sign sentence;
(3) with `e_sign: -1.0` and ex declared reversed (`azimuth_ex: 180.0`,
    `flip_reversed_dipoles` true), the archive's ex is not E1 negated (the
    reversed-dipole rule acts on the samples) with the same one stage of
    gain -1 in its chain (the convention), so that ex as calibrated
    (samples / `_scalar_gain`, and the products' response) is not +E1, the
    opposite sign of (1)'s calibrated ex sample for sample; or ey is not E2
    with calibrated -E2 as in (1); or ex's `measurement_azimuth` is not 0;
(4) a survey without the key (a LEMI-424 survey written before it existed)
    does not ingest as `e_sign: -1.0` does, sample for sample; or one
    declaring `channels: [e1, e2, bx, by, bz]` (the names before the rename)
    does not give the same archive channels and samples as the preset;
(5) `e_sign: 0.5` is accepted by `Survey.site`, or an EDL site's own entry
    with `e_sign: -1.0` is not refused by `mt_workbench.ingest._e_sign`
    while a `defaults:` value on that site is ignored (1.0);
(6) MBJ21 (one real hour, `channels` "E1 E2 Bx By Bz", e_sign -1.0) does not
    archive exactly ex ey hx hy hz with 3600 samples each, ex and ey not
    the file's E1 and E2 columns, hx not its Bx column, the lemi424_e_sign
    stage missing from ex or ey, or ex as `timefreq._scalar_gain` scales it
    not minus the file's E1;
(7) the LEMI-424 presets do not read: "E1 E2 E3 E4 Bx By Bz" ->
    [ex, ey, e3, e4, hx, hy, hz], "E1 E2 Bx By Bz" -> [ex, ey, hx, hy, hz],
    "Bx By Bz" -> [hx, hy, hz], each label back from its list by
    `preset_label`, and "bx by bz e1 e2" typed in another order not the
    second preset; or `INSTRUMENTS["lemi424"]["channels"]` is not
    hx hy hz ex ey e3 e4.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("lemi424_ingest")
SITE = "L01"
DAY_FILE = "202410250000.txt"
SENTENCE = ("LEMI-424 E sign convention e_sign -1 recorded in the chain of ex, ey (E1, E2 are recorded with the "
            "opposite sign to the x-north, y-east frame), the samples are the logger's columns")
# the reader's columns in a 24-field line: 6-8 Bx By Bz, 11-14 E1 E2 E3 E4
COLUMNS = {"hx": 6, "hy": 7, "hz": 8, "ex": 11, "ey": 12}


def write_day_file(path: Path, n: int = 5) -> None:
    """Write `n` one-second LEMI-424 lines from 2024-10-25 00:00:00 UTC, every value distinct."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for k in range(n):
        values = (27150.959 + k, -74.552 - 2 * k, -50540.593 + 3 * k, 27.73, 36.16,
                  -154.411 + 1.25 * k, 297.117 - 0.5 * k, 94.135 + k, -767.370 - k)
        lines.append("2024 10 25 00 00 {:02d} ".format(k) + " ".join(f"{v:.3f}" for v in values)
                     + " 12.00  512.8 2800.28816 S 12054.72277 E 12 2 0")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")


SURVEY = """\
name: lemi424_unit
instrument: lemi424
sample_rate: 1
data_root: {root}
workspace: {work}
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  # LEMI-424 sites: E1 and E2 are recorded with the opposite sign to the x-north, y-east frame
  e_sign: -1.0
  flip_reversed_dipoles: true
  channels: {channels}
sites:
  {site}:
    dipole_length_ex: 88.0
    dipole_length_ey: 100.0
    azimuth_ex: {azimuth_ex}
    azimuth_ey: 90.0
"""


def survey_file(name: str, root: Path, site: str, channels: str = "[ex, ey, hx, hy, hz]", azimuth_ex: float = 0.0,
                edit=None):
    """Write a survey.yaml for one LEMI-424 site and load it.

    Args:
        name (str): Folder name under the scratch folder for the yaml and its workspace.
        root (Path): The data root.
        site (str): The site.
        channels (str): The `channels:` value as YAML text.
        azimuth_ex (float): The site's Ex azimuth.
        edit (tuple of str, optional): (old, new) text replaced once in the yaml before it is loaded.

    Returns:
        Survey: The loaded survey.
    """
    from mt_workbench.survey import Survey

    folder = SCRATCH / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    text = SURVEY.format(root=root.as_posix(), work=(folder / "work").as_posix(), channels=channels, site=site,
                         azimuth_ex=azimuth_ex)
    if edit:
        assert text.count(edit[0]) == 1, edit
        text = text.replace(*edit)
    (folder / "survey.yaml").write_text(text, encoding="utf-8")
    return Survey.from_yaml(folder / "survey.yaml")


def read_archive(path: Path, site: str) -> dict:
    """Return what the checks need from an archive of one run.

    Returns:
        dict: channels, samples, chains (name, gain, units in, units out,
        applied), the stages aurora removes and their response at 0.01 Hz,
        the scalar gain `mt_workbench.timefreq._scalar_gain` divides by,
        dipole lengths, azimuths, tilts, the run comment, the run's channel
        list and the station's channels_recorded.
    """
    from aurora.time_series.spectrogram_helpers import get_calibration_filters
    from mth5.mth5 import MTH5

    from mt_workbench.timefreq import _scalar_gain

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        survey = m.surveys_group.groups_list[0]
        station = m.get_station(site, survey=survey)
        runs = [r for r in station.groups_list if r.startswith("sr")]
        assert len(runs) == 1, runs
        run = station.get_run(runs[0])
        out = {"channels": sorted(run.groups_list), "data": {}, "chain": {}, "removed": {}, "gain": {},
               "dipole": {},
               "azimuth": {}, "tilt": {}, "comment": str(run.metadata.comments.value or ""),
               "run_list": sorted(run.metadata.channels.keys()),
               "recorded": sorted(station.metadata.channels_recorded)}
        for comp in out["channels"]:
            ch = run.get_channel(comp)
            out["data"][comp] = ch.hdf5_dataset[()]
            applied = [bool(f.applied) for f in ch.metadata.filters]
            out["chain"][comp] = [(f.name, float(getattr(f, "gain", np.nan)), str(f.units_in), str(f.units_out), a)
                                  for f, a in zip(ch.channel_response.filters_list, applied)]
            response, removed = get_calibration_filters(run, comp)
            out["removed"][comp] = ([f.name for f in removed],
                                    complex(response.complex_response(np.array([0.01]), filters_list=removed)[0]))
            out["gain"][comp] = _scalar_gain(ch)
            out["dipole"][comp] = float(getattr(ch.metadata, "dipole_length", 0.0) or 0.0)
            out["azimuth"][comp] = float(ch.metadata.measurement_azimuth)
            out["tilt"][comp] = float(ch.metadata.measurement_tilt)
    finally:
        m.close_mth5()
    return out


def column(path: Path, comp: str) -> np.ndarray:
    """Return one channel's column of a LEMI-424 file, read here with numpy."""
    return np.loadtxt(path, usecols=COLUMNS[comp])


def ingest(survey, site: str) -> dict:
    """Ingest a site and read its archive back."""
    from mt_workbench.ingest import ingest_site

    return read_archive(ingest_site(survey, site, overwrite=True), site)


def part1() -> None:
    """Run checks (1)-(5) on the synthetic site."""
    from mt_workbench.ingest import _e_sign
    from mt_workbench.survey import Survey

    root = SCRATCH / "root"
    shutil.rmtree(root, ignore_errors=True)
    write_day_file(root / SITE / DAY_FILE)
    raw = root / SITE / DAY_FILE

    a = ingest(survey_file("minus", root, SITE), SITE)
    assert a["channels"] == ["ex", "ey", "hx", "hy", "hz"], a["channels"]
    for comp in ("hx", "hy", "hz"):
        assert np.array_equal(a["data"][comp], column(raw, comp)), (comp, a["data"][comp], column(raw, comp))
        assert a["chain"][comp] == [], (comp, a["chain"][comp])
    for comp in ("ex", "ey"):
        assert np.array_equal(a["data"][comp], column(raw, comp)), (comp, a["data"][comp], column(raw, comp))
        assert a["chain"][comp] == [("lemi424_e_sign", -1.0, "milliVolt per kilometer", "milliVolt per kilometer",
                                     True)], (comp, a["chain"][comp])
        assert a["removed"][comp] == (["lemi424_e_sign"], -1 + 0j), (comp, a["removed"][comp])
        assert a["gain"][comp] == (-1.0, False), (comp, a["gain"][comp])
        assert np.array_equal(a["data"][comp] / a["gain"][comp][0], -column(raw, comp)), comp
    assert SENTENCE in a["comment"], a["comment"]
    assert (a["dipole"]["ex"], a["dipole"]["ey"]) == (88.0, 100.0), a["dipole"]
    assert a["azimuth"] == {"ex": 0.0, "ey": 90.0, "hx": 0.0, "hy": 90.0, "hz": 0.0}, a["azimuth"]
    assert a["tilt"] == {"ex": 0.0, "ey": 0.0, "hx": 0.0, "hy": 0.0, "hz": 90.0}, a["tilt"]
    for listed in (a["run_list"], a["recorded"]):
        assert listed == ["ex", "ey", "hx", "hy", "hz"], listed
    print(f"(1) e_sign -1.0: channels {a['channels']}; ex, ey = E1, E2 and hx hy hz = Bx By Bz sample for "
          f"sample; ex chain {a['chain']['ex']}, aurora removes {a['removed']['ex']}; timefreq scalar gain "
          f"{a['gain']['ex']}, ex as plotted = -E1; dipoles {a['dipole']['ex']:g}/"
          f"{a['dipole']['ey']:g} m; azimuths {a['azimuth']}; tilts {a['tilt']}; run list and station "
          f"channels_recorded {a['recorded']}; run comment carries the sentence")

    b = ingest(survey_file("plus", root, SITE, edit=("  e_sign: -1.0\n", "  e_sign: 1.0\n")), SITE)
    for comp in ("ex", "ey"):
        assert np.array_equal(b["data"][comp], column(raw, comp)), (comp, b["data"][comp])
        assert b["chain"][comp] == [], (comp, b["chain"][comp])
        assert b["gain"][comp] == (1.0, False), (comp, b["gain"][comp])
        assert b["removed"][comp] == ([], 1 + 0j), (comp, b["removed"][comp])
        # the stage alone sets the sign timefreq draws: -1 with it (1), +1 without it (here)
        assert a["gain"][comp][0] == -1.0 * b["gain"][comp][0], (a["gain"][comp], b["gain"][comp])
    assert "e_sign" not in b["comment"], b["comment"]
    print("(2) the one-line change to e_sign: 1.0: ex, ey = E1, E2 unchanged, no stage, scalar gain +1 (-1 times "
          "(1)'s), aurora removes nothing, no sentence")

    c = ingest(survey_file("reversed", root, SITE, azimuth_ex=180.0), SITE)
    assert np.array_equal(c["data"]["ex"], -column(raw, "ex")), c["data"]["ex"]
    assert np.array_equal(c["data"]["ey"], column(raw, "ey")), c["data"]["ey"]
    assert c["chain"]["ex"] == a["chain"]["ex"] and c["removed"]["ex"] == a["removed"]["ex"], c["chain"]["ex"]
    for comp, sign in (("ex", -1.0), ("ey", 1.0)):  # calibrated: the declared line the opposite of (1), the other as (1)
        assert np.array_equal(c["data"][comp] / c["gain"][comp][0], sign * a["data"][comp] / a["gain"][comp][0]), comp
    assert np.array_equal(c["data"]["ex"] / c["gain"]["ex"][0], column(raw, "ex"))
    assert c["azimuth"]["ex"] == 0.0, c["azimuth"]
    print("(3) e_sign -1.0 with azimuth_ex 180: the archive's ex = -E1 (the reversed line in the samples), its chain "
          "the -1 stage (the convention), calibrated ex = +E1, the opposite of (1)'s; ey = E2, calibrated -E2 as "
          "(1); ex azimuth 0 (the frame stored)")

    d = ingest(survey_file("nokey", root, SITE, edit=("  e_sign: -1.0\n", "")), SITE)
    e = ingest(survey_file("oldnames", root, SITE, channels="[e1, e2, bx, by, bz]"), SITE)
    for other, label in ((d, "no e_sign key"), (e, "channels [e1, e2, bx, by, bz]")):
        assert other["channels"] == a["channels"], (label, other["channels"])
        for comp in a["channels"]:
            assert np.array_equal(other["data"][comp], a["data"][comp]), (label, comp)
        assert other["chain"]["ex"] == a["chain"]["ex"], (label, other["chain"]["ex"])
    print("(4) no e_sign key, and channels in the reader's old names: the same archive as e_sign -1.0 with the preset")

    try:
        survey_file("half", root, SITE, edit=("  e_sign: -1.0\n", "  e_sign: 0.5\n")).site(SITE)
    except ValueError as exc:
        assert "e_sign" in str(exc), exc
    else:
        raise AssertionError("e_sign 0.5 was accepted")
    config = {"name": "t", "instrument": "edl", "data_root": str(root), "defaults": {"e_sign": -1.0},
              "sites": {"E01": {"e_sign": -1.0}, "E02": {}}}
    edl = Survey(config, SCRATCH)
    try:
        _e_sign(edl, edl.site("E01"), "edl")
    except ValueError as exc:
        assert "e_sign" in str(exc) and "edl" in str(exc), exc
    else:
        raise AssertionError("an EDL site's own e_sign -1.0 was not refused")
    assert _e_sign(edl, edl.site("E02"), "edl") == 1.0
    print("(5) e_sign 0.5 refused by Survey.site; an EDL site's own e_sign -1.0 refused at ingest, the defaults "
          "value on an EDL site ignored (1.0)")


def part2() -> None:
    """Run check (6) on one real hour of MBJ21."""
    import instrument_samples

    sample = instrument_samples.make_samples()["MBJ21"]
    root = SCRATCH / "real_root"
    shutil.rmtree(root, ignore_errors=True)
    shutil.copytree(sample, root / "MBJ21")
    raw = root / "MBJ21" / instrument_samples.LEMI424_FILE
    got = ingest(survey_file("real", root, "MBJ21"), "MBJ21")
    assert got["channels"] == ["ex", "ey", "hx", "hy", "hz"], got["channels"]
    assert all(got["data"][c].shape == (3600,) for c in got["channels"]), {c: got["data"][c].shape for c in got["data"]}
    for comp in ("ex", "ey"):
        assert np.array_equal(got["data"][comp], column(raw, comp)), comp
        assert [s[0] for s in got["chain"][comp]] == ["lemi424_e_sign"], got["chain"][comp]
        assert np.array_equal(got["data"][comp] / got["gain"][comp][0], -column(raw, comp)), comp
    assert np.array_equal(got["data"]["hx"], column(raw, "hx"))
    print(f"(6) MBJ21, one real hour: {got['channels']}, 3600 samples each; ex, ey = E1, E2 and hx = Bx sample "
          f"for sample; as timefreq scales them, ex, ey = -E1, -E2; e3, e4 and the temperatures left out; ex chain "
          f"{[s[0] for s in got['chain']['ex']]}")


def part3() -> None:
    """Run check (7), the presets."""
    from mt_workbench.instruments import INSTRUMENTS
    from mt_workbench.survey import CHANNEL_PRESETS, channels_from_label, preset_label

    want = {"E1 E2 E3 E4 Bx By Bz": ["ex", "ey", "e3", "e4", "hx", "hy", "hz"],
            "E1 E2 Bx By Bz": ["ex", "ey", "hx", "hy", "hz"], "Bx By Bz": ["hx", "hy", "hz"]}
    assert CHANNEL_PRESETS["lemi424"] == want, CHANNEL_PRESETS["lemi424"]
    for label, names in want.items():
        assert channels_from_label(label, "lemi424") == names, label
        assert preset_label(names, "lemi424") == label, (names, preset_label(names, "lemi424"))
    assert channels_from_label("bx by bz e1 e2", "lemi424") == want["E1 E2 Bx By Bz"]
    assert INSTRUMENTS["lemi424"]["channels"] == ("hx", "hy", "hz", "ex", "ey", "e3", "e4")
    print(f"(7) presets {want}, each label read back; INSTRUMENTS channels {INSTRUMENTS['lemi424']['channels']}")


def main() -> int:
    """Run parts 1 to 3 and return 0."""
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    part1()
    part2()
    part3()
    print("\nPASS  lemi424_ingest_unit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
