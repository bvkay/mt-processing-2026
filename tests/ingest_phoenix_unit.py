# -*- coding: utf-8 -*-
"""
Unit test for the Phoenix reader of mt-workbench (mt_workbench.phoenix)

Cuts of two real recordings are copied, read only, from the Kalkaroo
Phoenix test folder (`SOURCE`) into scratch, in
the receiver's folder layout: the JSON files, backend.log and config.json,
and the first 3 `.td_150` and first 2 `.td_24k` files of every channel
folder. G5 is an MTU-8A (receiver 10133, folders 0 E1, 2 H2, 3 H1, 7 E2),
J1 an MTU-5C (receiver 10240, folders 0 H2, 1 E1, 2 H1, 4 E2). A third cut,
G5T, is G5 with file 2 of every channel truncated by 60 s. Each cut is a
site of a scratch survey (instrument phoenix, 150 Hz, `calibration_dir`
the test folder's sensors) and is ingested with `ingest_site` into a
scratch workspace; the archives are read back with mth5 and compared with
the file bytes read here with numpy, never through the reader under test.

Usage:
    python tests/ingest_phoenix_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - U1: a G5 channel's samples differ from `np.fromfile(file, "<f4",
    offset=128)` of its folder's files joined in sequence order, with ex
    from folder 0, ey 7, hx 3 and hy 2;
  - U2: the same holds for J1 with ex 1, ey 4, hx 2 and hy 0;
  - U3: any file's samples differ from `open_phoenix(fn).read()`; or the
    burst archive G5H (`bursts_of: G5`) does not hold one run per burst,
    24 for the cut's two `.td_24k` files (the count of a walk of the
    sub-headers done here with `struct`: offset 128, `<II` stamp and
    count, step 32 + 4n), each channel's samples equal to the walk's bytes
    and to mt-io's `DecimatedSegmentCollection(fn).to_channel_ts()[k]`;
  - U4: the first sample's time is not the recording id in the file
    names less 18 leap seconds, plus 1 s (mt-io's start of file 1) and
    plus the 1 s file-version-2 correction, to the nanosecond; or the
    line "phoenix_stamp_correction_s: 1.0 s added ..." is missing from the
    run comment, a channel comment or the station's provenance comments;
    or a burst run's first sample is not its stamp less 18 s plus 1 s, or
    its run comment, channel comments or the station lack the line; or the
    burst station's `time_period.start` is not its first run's start and
    the first stamp less 18 s plus 1 s, to the nanosecond, or its
    `time_period.end` not its last run's end and, to 1 us, the last stamp
    less 18 s plus 1 s plus (n - 1) / 24000 s;
  - U5: G5's hx stage is not `phoenix_coil_53508` (empower_recmeta.json's
    serial, not recmeta.json's 54047), its response at the table's own
    frequencies differs by more than 1e-9 relative from the magnitude and
    phase of 53508's scal JSON read here with `json`, or hx's comment does
    not name empower_recmeta.json, recmeta.json 54047 and self-report
    53508; J1 without an override does not get 54870 with "coil
    self-report differs" and self-report 53674 in the comment, or J1 with
    `coil_hx: '53674'` does not get `phoenix_coil_53674` and "from
    survey.yaml". The coil's `polInv` flag, which mt-io does not read
    (upstream issue 54), is only recorded in the comment; U5 does not
    check a sign;
  - U6: at 0.1, 1 and 10 Hz (points of both tables), |chain| / |receiver
    curve| is not L x 1e-6 for G5's ex (L = 100 m) and ey (85 m), and the
    scal table's magnitude x 1e-3 for hx, to 1e-9 relative; a chain's
    units are not mV/km or nT in and V out; or mt_timeseries'
    `RunTS.calibrate` logs "Unexpected Inverse Filter" or "likely corrupt";
  - U7: G5's ey is not 85 m (empower_recmeta.json, against recmeta.json's
    100) with no key, or not 100 m with `dipole_length_ey: 100` with the
    comment naming survey.yaml and empower_recmeta.json 85;
  - U8: the G5T cut does not give two runs, the first of files 1-2 and
    the second of file 3 starting at the recording id - 18 + 720 + 1 s;
  - U9: `ingest_site` accepts a site entry with an unknown key (`model`),
    `h_scale` on a Phoenix site, a `serial` other than the recording's
    receiver, or a burst entry with `dipole_length_ex`; or a `.td_2400`
    file in a channel folder stops the ingest or leaves the run comment
    without "phoenix_unread: .td_2400 files not read";
  - U10: G5 declared at 1000 Hz is ingested, or G5H's archive is not at
    24000 Hz with run ids sr24000_00001 to sr24000_00024;
  - U11: the station of the G5 or G5H archive lists a channel under
    mt-io's own tag (e1, e2, h1, h2) in `channels_recorded`, or a run in
    `run_list` that the station does not hold (aurora's export stops on an
    e1 there);
  - U12: with mt-io's reader made to date every file 1 s later (as a
    reader that corrects the version-2 second would: `segment_start_time`
    of `open_phoenix` for G5, each segment's `gps_time_stamp` of
    `DecimatedSegmentCollection.read_segments` for G5H), G5's first sample
    is not at the recording id - 18 + 1 + 1 s, or a G5H burst's not at
    its stamp - 18 + 1 s, or the G5H station's period not as in U4, or the
    line "phoenix_stamp_correction_s: 0.0 s added" is missing from a run,
    channel or station comment; or, with mt-io's dates 0.5 s later
    instead, either ingest is accepted or its error does not name a
    `.td_150` (G5) or `.td_24k` (G5H) file;
  - U13 (upstream issue 73): on G5C, G5 with the second `.td_24k` file of
    every channel folder cut to end `CUT_SAMPLES` samples into its last
    burst (as PT_10306's last file ends 24000 samples into its sixth
    burst), the burst site G5CH is refused, does not hold one run per
    whole burst (23: the cut one left out), a run's samples differ from
    the walk's bytes of its burst, or no warning names the cut file; or a
    failure forced inside `_ingest_bursts` after five runs are written
    (`stamp_correction` raising) does not propagate, or leaves G5CH.h5 or
    any other G5CH file in the workspace;
  - U14: with G5 declaring `clock_offset_s: -0.1148` (the Kalkaroo
    continuous stream's delay), a G5H burst run's first sample is not its
    stamp - 18 + 1 s (the version-2 correction only) to the nanosecond, or
    a G5H run or channel comment carries a "clock_offset_s:" line; with
    G5H declaring its own 0.05, a run's first sample is not its stamp
    - 18 + 1 + 0.05 s to 1 us, or the line is missing; or G5's continuous
    run under the same survey does not start at the recording id - 18 + 1
    + 1 - 0.1148 s to 1 us (the control: the recorded site keeps its
    offset);
  - U15 (upstream issues 76 and 77, the S1 sites J12 and E10): on cuts of
    G5's first `.td_150` files, G5Z (three files and a 0-byte sequence 4 in
    every folder) is not ingested as one run of files 1-3 with a warning
    naming each of the four empty files; G5M (four files, sequence 2
    deleted from the hx folder 3) and G5E (sequence 2 of folder 3 cut to
    0 bytes, named in a warning) are not ingested as two runs, files 1
    and 3-4, with every channel of a run as long as the others, each
    channel's samples equal to its own folder's files of those sequences
    (np.fromfile), every channel of run 2 starting at sequence 3's time
    (the recording id - 18 + 720 + 1 s, to the ns), and run 2's comment
    holding the "phoenix_gap:" line with sequence 2, folder 3 and 360 s;
  - U17 (upstream issue 78), on the runs of U15: a run comment's dc level
    record does not give back (`dclevel.parse_level_note`) the input rail
    of each channel, 0.9 x 5 V / the header's total circuitry gain: 2.25 V
    for ex and ey, 1.125 V for hx and hy; or a ";"-piece of a run comment
    has a dot in its key (before its first ":"), which stops the EMTF XML
    writer (upstream issue 82);
  - U16: the run plans of the 25 recordings of the test folder
    (`plan_runs` of `recording_files`, every `.td_150` type) differ from
    tests/fixtures/phoenix_plans/ptest_plans.json, written by the code of
    8a72107 before the gap fix, in sequences, first sample, samples,
    folders or alignment, or any of them carries a gap note;
  - U18 (the Phoenix H polarity, upstream issue 81): G5's hx or hy chain
    does not hold one `phoenix_h_polarity` CoefficientFilter of gain -1, or
    ex or ey holds one; an hx or hy comment lacks "phoenix_h_polarity -1";
    the chain's response at 1 Hz is not at 180 +- 10 deg for hx and hy (the
    coil adds +3.9 deg) and 0 +- 1 deg for ex and ey, or an H chain over the
    same chain without the stage is not -1 to 1e-12; hx's stored samples
    differ from the file bytes; the band-passed (0.5-10 Hz) zero-lag
    correlation of a stored channel with the same channel calibrated (its
    spectrum divided by the archive chain's response, as aurora does; for
    hx and hy also through mt_timeseries' `RunTS.calibrate`) is not below
    -0.9 for hx and hy and above +0.9 for ex and ey; with `flip_h: [hy]`
    the stored hy is not
    minus the file bytes, its chain not the unflipped hy's, or its
    calibrated series not correlated below -0.99 with the unflipped hy's
    calibrated; with `swap_h: true` hx or hy does not hold the stage once;
    or G5H's first burst run does not hold it once on hx and hy and not on
    ex; or, with `phoenix._coil_stage` giving no coil table (62 Kalkaroo
    channels have none), the ingest of G5 fails, hx's or hy's chain is not
    [`phoenix_h_polarity` of gain -1, `phoenix_mv_to_v`, the receiver
    curve], or mt_metadata's `ChannelResponse` refuses its units;
  - U19 (upstream issue 85): ingesting G5H's first 12 bursts and all 24,
    with mth5's `StationGroup.metadata` getter and mt_metadata's
    `Station.update_all` wrapped to count their calls, either archive does
    not hold the window's runs, the getter is called more than
    `MAX_STATION_READS` times or once while the station holds a run (each
    such call adds every run to the station again, each add a pass over all
    its runs), or the getter's or update_all's count differs between the
    two ingests (grows with the run count).

The mutations, each of which must trip its check: U1 with e1 and e2
renamed the wrong way round; U2 with mt-io's default channel map (the map
the reader falls back to with no metadata file) in place of the
recording's; U4 with the correction dropped (1 s early) and applied twice
(1 s late), for the bursts as for the continuous runs, where the burst
station's start must then be 1 s off as well; U3 with the bursts
read through `read_phoenix` (the installed mt-io's first burst only: 2
runs); U5 with the coil serial taken from recmeta.json; U6 with
mt-io's `v_to_mv` kept (off by 10^6); U7 with the dipole length taken
from recmeta.json; U8 with files joined whatever their starts (one run,
run 2's samples 60 s early); U9 with the refusal of `h_scale` removed;
U10 with the header rate check removed; U11 with mt-io's station and run
records kept (`station_record` a no-op but for the id, `run_record` a no-op);
U12 with `stamp_correction` returning `STAMP_CORRECTION_S` whenever the
file version is below 3, whatever mt-io's start (the +1 s case then starts
1 s late, for G5 and for G5H, and so does the G5H station); U13 with
`phoenix.cut_burst_samples` returning None (mt-io's cut burst compared
again, the ingest refused) and with `ingest._remove_partial_archive` a
no-op (the partial G5CH.h5 left). The U13 mutations run only when U13
passes. U14 with
`Survey._burst_site` copying the recorded site's offset (the rule of
a035bc7: the bursts 0.1148 s early). U15 with `phoenix._aligned_files`
keeping each folder's own files (G5M refused or misaligned); U16 with
`phoenix._JOIN_TOLERANCE_SAMPLES` below 0 (every file its own run). The
U15 and U16 mutations run only when their checks pass; on 8a72107 U15
fails (both ingests refused). U18 with the stage's gain made +1
(`phoenix.H_POLARITY_GAIN`) and with no stage (`phoenix._h_polarity_stage`
returning None); both run only when U18 passes, and on 4beb3cd U18 fails.
U18's coil-missing case with the stage labelled nT in, nT out (which
would have to stand before a coil stage): the chain must be refused. U19
with a station read per run restored (mth5's `StationGroup.add_run` made to
read the station's `metadata` after adding the run: the getter's count
grows with the runs) and with the station written through mth5's own
`write_metadata` (`ingest._write_group_metadata` replaced: one getter call
with the runs present, update_all once per run); both run only when U19
passes, and on e56af1c U19 itself fails (five getter calls with the runs
present, update_all five times per run).
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import mt_workbench.ingest as ingest  # noqa: E402
import mt_workbench.phoenix as phoenix  # noqa: E402
from mt_workbench.dclevel import parse_level_note  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.timefreq import _real_runs  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SOURCE = Path(r"D:\MT_DATA\MT_Kalkaroo_Phoenix_TEST")
SENSORS = SOURCE / "sensors"
SCRATCH = scratch_dir("ingest_phoenix_unit")
DATA = SCRATCH / "data"
LEAP = 18
# expected folder of each stored channel, by receiver model
MAPS = {"G5": {"ex": 0, "ey": 7, "hx": 3, "hy": 2}, "J1": {"ex": 1, "ey": 4, "hx": 2, "hy": 0}}
TRUNCATE_S = 60
CUT_SAMPLES = 24000  # samples the cut last burst of G5C keeps
SITE_FILES = ("empower_recmeta.json", "recmeta.json", "backend.log", "config.json")
WORKSPACE = SCRATCH / "workspace"
# U19: the most station getter calls a burst ingest may make (all before its first run)
MAX_STATION_READS = 4


def survey_for(site: str, entry: dict | None = None, rate: float = 150.0, extra: dict | None = None) -> Survey:
    """Return a scratch survey of the cuts with one site's entry set."""
    sites = {site: dict(entry or {}), **(extra or {})}
    config = {"name": "PHOENIX_TEST", "instrument": "phoenix", "sample_rate": rate, "data_root": str(DATA),
              "workspace": str(WORKSPACE),
              "defaults": {"calibration_dir": str(SENSORS), "channels": ["ex", "ey", "hx", "hy"]},
              "sites": sites}
    return Survey(config, SCRATCH)


def make_cut(site: str, name: str | None = None, n150: int = 3, n24: int = 2, truncate: int | None = None) -> Path:
    """Copy the first files of each channel folder of a test recording into scratch.

    Args:
        site (str): The test folder's site.
        name (str, optional): The cut's folder name; the site's by default.
        n150 (int): `.td_150` files per channel folder.
        n24 (int): `.td_24k` files per channel folder.
        truncate (int, optional): Sequence number of a file cut short by
            `TRUNCATE_S` seconds in every channel folder.

    Returns:
        Path: The cut's folder.
    """
    src, dst = SOURCE / site, DATA / (name or site)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for fname in SITE_FILES:
        if (src / fname).exists():
            shutil.copy2(src / fname, dst / fname)
    for folder in sorted(p for p in src.iterdir() if p.is_dir() and p.name.isdigit()):
        (dst / folder.name).mkdir()
        for ext, count in ((".td_150", n150), (".td_24k", n24)):
            for f in sorted(folder.glob(f"*{ext}"), key=lambda p: int(p.stem.split("_")[3], 16))[:count]:
                shutil.copy2(f, dst / folder.name / f.name)
                if truncate and ext == ".td_150" and int(f.stem.split("_")[3], 16) == truncate:
                    with open(dst / folder.name / f.name, "r+b") as handle:
                        handle.truncate(f.stat().st_size - TRUNCATE_S * 150 * 4)
    return dst


def rec_id(cut: Path) -> int:
    """Return the recording id (GPS seconds) from a cut's file names."""
    first = next(cut.glob("*/*.td_150"))
    return int(first.stem.split("_")[1], 16)


def file_bytes(cut: Path, folder: int, sequences) -> np.ndarray:
    """Return a channel folder's samples read with numpy past the 128-byte header, files joined."""
    files = sorted((cut / str(folder)).glob("*.td_150"), key=lambda p: int(p.stem.split("_")[3], 16))
    keep = [f for f in files if int(f.stem.split("_")[3], 16) in sequences]
    return np.concatenate([np.fromfile(f, dtype="<f4", offset=128) for f in keep])


def comment_text(value) -> str:
    """Return a comment's text, whether it is held as text, a dict or a Comment."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(getattr(value, "value", value) or "")


def read_runs(cut: Path, site: str, entry: dict | None = None, keep_run: bool = False) -> list[dict]:
    """Ingest a cut with `ingest_site` and read its archive back with mth5, as plain dicts per run.

    Returns:
        list of dict: Per run, ``start_ns``, ``sequences`` (from the run
        comment's "files a-b"), ``data`` {comp: samples}, ``run_comment``,
        ``channel_comments`` {comp: text}, ``station_comment``, ``chains``
        {comp: filter names}, ``filters`` {name: filter} and, with
        `keep_run`, ``run`` (the run group's RunTS).
    """
    import re
    from mth5.mth5 import MTH5

    assert cut.name == site, (cut, site)
    path = ingest_site(survey_for(site, entry), site, overwrite=True)
    m = MTH5()
    m.open_mth5(path, mode="r")
    out = []
    try:
        survey_name = m.surveys_group.groups_list[0]
        station = m.get_station(site, survey=survey_name)
        station_comment = str(station.metadata.provenance.comments.value or "")
        for run_id, _s, _e in _real_runs(station):
            group = station.get_run(run_id)
            comment = str(group.metadata.comments.value or "")
            first, last = re.search(r"files (\d+)-(\d+)", comment).groups()
            data, comments, chains, filters, start, starts = {}, {}, {}, {}, None, {}
            for comp in group.groups_list:
                ch = group.get_channel(comp)
                data[comp] = np.asarray(ch.hdf5_dataset[()])
                comments[comp] = comment_text(ch.metadata.comments)
                chains[comp] = [f.name for f in ch.metadata.filters]
                filters.update({f.name: f for f in ch.channel_response.filters_list})
                start = starts[comp] = int(pd.Timestamp(str(ch.metadata.time_period.start)).value)
            out.append({"start_ns": start, "starts": starts, "sequences": list(range(int(first), int(last) + 1)),
                        "data": data,
                        "run_comment": comment, "channel_comments": comments, "station_comment": station_comment,
                        "chains": chains, "filters": filters, "run": group.to_runts() if keep_run else None})
    finally:
        m.close_mth5()
    return out


def scal_table(serial: str) -> tuple[np.ndarray, np.ndarray]:
    """Return a coil's table from its scal JSON, read with json: frequencies and complex mV/nT."""
    import json

    path = next(SENSORS.glob(f"{serial}_*.scal.json"))
    data = json.loads(path.read_text())["cal_data"][0]["chan_data"][0]
    freq = np.asarray(data["freq_Hz"], dtype=float)
    return freq, np.asarray(data["magnitude"]) * np.exp(1j * np.radians(np.asarray(data["phs_deg"])))


def check_coils(g5: Path, j1: Path) -> list[str]:
    """U5: coil stages, responses and comment sources. Returns the failures."""
    bad = []
    run = read_runs(g5, "G5", keep_run=True)[0]
    if run["chains"]["hx"][0] != "phoenix_coil_53508":
        bad.append(f"G5 hx stage {run['chains']['hx'][0]}, expected phoenix_coil_53508")
    else:
        freq, table = scal_table("53508")
        got = run["filters"]["phoenix_coil_53508"].complex_response(freq)
        err = float(np.max(np.abs(got - table) / np.abs(table)))
        if err > 1e-9:
            bad.append(f"G5 hx coil response differs from the scal table by {err:.2e} relative")
    text = run["channel_comments"]["hx"]
    for want in ("coil 53508 from empower_recmeta.json", "recmeta.json 54047", "self-report 53508"):
        if want not in text:
            bad.append(f"G5 hx comment lacks {want!r}: {text[:160]}")
    plain = read_runs(j1, "J1")[0]
    text = plain["channel_comments"]["hx"]
    if plain["chains"]["hx"][0] != "phoenix_coil_54870" or "coil self-report differs" not in text \
            or "self-report 53674" not in text:
        bad.append(f"J1 hx without override: {plain['chains']['hx'][0]}, {text[:200]}")
    override = read_runs(j1, "J1", {"coil_hx": "53674"})[0]
    text = override["channel_comments"]["hx"]
    if override["chains"]["hx"][0] != "phoenix_coil_53674" or "coil 53674 from survey.yaml" not in text:
        bad.append(f"J1 hx with coil_hx 53674: {override['chains']['hx'][0]}, {text[:200]}")
    return bad


def check_units(g5: Path) -> list[str]:
    """U6: the chain's scale against the units arithmetic, its units, and calibrate's warnings."""
    from mt_metadata.timeseries.filters import ChannelResponse

    bad = []
    run = read_runs(g5, "G5", keep_run=True)[0]
    filters = run["filters"]
    freq = np.array([0.1, 1.0, 10.0])
    sfreq, table = scal_table("53508")
    coil_mag = np.array([abs(table[np.argmin(np.abs(sfreq - f))]) for f in freq])
    for comp, want in (("ex", np.full(3, 100 * 1e-6)), ("ey", np.full(3, 85 * 1e-6)), ("hx", coil_mag * 1e-3)):
        names = run["chains"][comp]
        response = ChannelResponse(filters_list=[filters[n] for n in names])
        rx = filters[names[-1]].complex_response(freq)
        ratio = np.abs(response.complex_response(freq, filters_list=response.filters_list)) / np.abs(rx)
        err = float(np.max(np.abs(ratio / want - 1)))
        if err > 1e-9:
            bad.append(f"{comp}: |chain| / |rx| = {ratio} against {want} ({err:.2e})")
        units_in = "milliVolt per kilometer" if comp.startswith("e") else "nanoTesla"
        if (response.units_in, response.units_out) != (units_in, "Volt"):
            bad.append(f"{comp}: chain units {response.units_in} -> {response.units_out}")
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="DEBUG")
    try:
        run["run"].calibrate()
    finally:
        logger.remove(sink)
    hits = [m.strip() for m in messages if "Unexpected Inverse Filter" in m or "likely corrupt" in m]
    if hits:
        bad.append(f"calibrate: {hits[0][:160]}")
    return bad


def check_dipoles(g5: Path) -> list[str]:
    """U7: the dipole lengths and their sources. Returns the failures."""
    bad = []
    plain = read_runs(g5, "G5")[0]
    if plain["chains"]["ey"][0] != "dipole_85m" or "dipole 85 m from empower_recmeta.json" not in plain["channel_comments"]["ey"]:
        bad.append(f"G5 ey with no key: {plain['chains']['ey'][0]}, {plain['channel_comments']['ey'][:120]}")
    declared = read_runs(g5, "G5", {"dipole_length_ey": 100.0})[0]
    text = declared["channel_comments"]["ey"]
    if declared["chains"]["ey"][0] != "dipole_100m" or "dipole 100 m from survey.yaml, empower_recmeta.json 85" not in text:
        bad.append(f"G5 ey with dipole_length_ey 100: {declared['chains']['ey'][0]}, {text[:120]}")
    return bad


def check_map(cut: Path, site: str) -> list[str]:
    """U1/U2: every stored channel equals its folder's file bytes. Returns the failures."""
    bad = []
    try:
        runs = read_runs(cut, site)
    except Exception as exc:  # a wrong map can stop the read; that is a failure of the check
        return [f"{site}: read failed: {exc}"]
    run = runs[0]
    for comp, folder in MAPS[site].items():
        if comp not in run["data"]:
            bad.append(f"{site} {comp}: not stored ({sorted(run['data'])})")
            continue
        want = file_bytes(cut, folder, run["sequences"])
        if not np.array_equal(run["data"][comp].astype("<f4"), want):
            bad.append(f"{site} {comp}: samples differ from folder {folder}")
    return bad


def check_reader(cut: Path) -> list[str]:
    """U3: each file's samples through `open_phoenix(fn).read()` equal the file bytes."""
    from mt_io.phoenix.read import open_phoenix

    bad = []
    for f in sorted(cut.glob("*/*.td_150")):
        reader = open_phoenix(f)
        try:
            got = reader.read()
        finally:
            reader.close()
        if not np.array_equal(got, np.fromfile(f, dtype="<f4", offset=128)):
            bad.append(f.name)
    return bad


def check_stamps(cut: Path, site: str) -> list[str]:
    """U4: the first sample's time and the comment lines. Returns the failures."""
    run = read_runs(cut, site)[0]
    want = (rec_id(cut) - LEAP + 1 + 1) * 10**9
    bad = []
    if run["start_ns"] != want:
        bad.append(f"{site}: first sample {pd.Timestamp(run['start_ns'], unit='ns')} != "
                   f"{pd.Timestamp(want, unit='ns')} ({(run['start_ns'] - want) / 1e9:+.3f} s)")
    line = "phoenix_stamp_correction_s: 1.0 s added to every time stamp"
    if line not in run["run_comment"]:
        bad.append(f"{site}: run comment lacks the stamp line")
    for comp, text in run["channel_comments"].items():
        if line not in text:
            bad.append(f"{site} {comp}: channel comment lacks the stamp line")
    if line not in run["station_comment"]:
        bad.append(f"{site}: station comment lacks the stamp line")
    return bad


def check_split(cut: Path) -> list[str]:
    """U8: the truncated cut gives two runs, the second dated by its own file. Returns the failures."""
    runs = read_runs(cut, "G5T")
    bad = []
    if [r["sequences"] for r in runs] != [[1, 2], [3]]:
        bad.append(f"runs {[r['sequences'] for r in runs]}, expected [[1, 2], [3]]")
    if len(runs) > 1:
        want = (rec_id(cut) - LEAP + 720 + 1) * 10**9
        if runs[1]["start_ns"] != want:
            bad.append(f"run 2 starts {(runs[1]['start_ns'] - want) / 1e9:+.3f} s from the recording id - 18 + 720 + 1 s")
        if not np.array_equal(runs[1]["data"]["ex"].astype("<f4"), file_bytes(cut, 0, [3])):
            bad.append("run 2 ex is not file 3's samples")
    return bad


def refusal(site: str, entry: dict, rate: float = 150.0, extra: dict | None = None, ingest_as: str | None = None) -> str:
    """Return the ValueError text of an ingest, or "ACCEPTED" when the ingest wrote an archive."""
    try:
        ingest_site(survey_for(site, entry, rate, extra), ingest_as or site, overwrite=True)
    except ValueError as exc:
        return str(exc)
    return "ACCEPTED"


def check_keys(g5: Path) -> list[str]:
    """U9: key refusals and the td_2400 note. Returns the failures."""
    bad = []
    cases = {"unknown key": ({"model": "MTU-8A"}, "'model'"), "h_scale": ({"h_scale": -1000.0}, "h_scale"),
             "serial": ({"serial": "10134"}, "receiver 10133")}
    for label, (entry, word) in cases.items():
        text = refusal("G5", entry)
        if text == "ACCEPTED" or word not in text:
            bad.append(f"{label}: {text[:120]}")
    text = refusal("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000, "dipole_length_ex": 50.0}},
                   ingest_as="G5H")
    if text == "ACCEPTED" or "dipole_length_ex" not in text:
        bad.append(f"dipole_length_ex on G5H: {text[:120]}")
    fake = g5 / "0" / next((g5 / "0").glob("*.td_24k")).name.replace(".td_24k", ".td_2400")
    shutil.copy2(next((g5 / "0").glob("*.td_24k")), fake)
    try:
        comment = read_runs(g5, "G5")[0]["run_comment"]
    except Exception as exc:
        comment = f"stopped: {exc}"
    finally:
        fake.unlink()
    if "phoenix_unread: .td_2400 files not read (no mt-io reader)" not in comment:
        bad.append(f"td_2400: {comment[:160]}")
    return bad


def walk_bursts(path: Path) -> list[tuple[int, np.ndarray]]:
    """Return a .td_24k file's whole bursts by walking its sub-headers with struct: (stamp, samples)."""
    import struct

    raw = path.read_bytes()
    out, offset = [], 128
    while offset + 32 <= len(raw):
        stamp, n = struct.unpack_from("<II", raw, offset)
        if offset + 32 + 4 * n > len(raw):  # a burst cut at the end of the file (U13)
            break
        out.append((stamp, np.frombuffer(raw, dtype="<f4", count=n, offset=offset + 32)))
        offset += 32 + 4 * n
    return out


def read_bursts_archive(path: Path, site: str) -> dict:
    """Read a burst archive back with mth5.

    Returns:
        dict: ``runs`` {run id: ``start_ns`` (the channels'), ``period_ns``
        (the run's own start and end), ``data``, ``channel_comments``,
        ``rate``, ``run_comment``}, ``station_comment`` and
        ``station_period_ns`` (the station's start and end).
    """
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    runs = {}
    try:
        survey_name = m.surveys_group.groups_list[0]
        station = m.get_station(site, survey=survey_name)
        station_comment = str(station.metadata.provenance.comments.value or "")
        station_period = ns_period(station.metadata.time_period)
        for run_id in sorted(r for r in station.groups_list if r.startswith("sr")):
            group = station.get_run(run_id)
            data, comments, start, rate = {}, {}, None, None
            for comp in group.groups_list:
                ch = group.get_channel(comp)
                data[comp] = np.asarray(ch.hdf5_dataset[()])
                comments[comp] = comment_text(ch.metadata.comments)
                start = int(pd.Timestamp(str(ch.metadata.time_period.start)).value)
                rate = float(ch.metadata.sample_rate)
            runs[run_id] = {"start_ns": start, "period_ns": ns_period(group.metadata.time_period), "data": data,
                            "channel_comments": comments, "rate": rate,
                            "run_comment": str(group.metadata.comments.value or "")}
    finally:
        m.close_mth5()
    return {"runs": runs, "station_comment": station_comment, "station_period_ns": station_period}


def ns_period(period) -> tuple[int, int]:
    """Return a metadata `time_period`'s start and end as integer nanoseconds."""
    return int(pd.Timestamp(str(period.start)).value), int(pd.Timestamp(str(period.end)).value)


def check_station_period(got: dict, label: str, first_ns: int, last_end_ns: int) -> list[str]:
    """U4 and U12: a burst station's period against its runs and the stamps. Returns the failures.

    The station's start must equal its first run's start and `first_ns`;
    its end its last run's end and `last_end_ns` to 1 us (a sample at
    24 kHz is 41.7 us).

    Args:
        got (dict): The archive as `read_bursts_archive` returns it.
        label (str): The start of each failure line.
        first_ns (int): The first burst's first sample from its stamp, ns.
        last_end_ns (int): The last burst's last sample from its stamp, ns.

    Returns:
        list of str: The failures.
    """
    runs = [got["runs"][k]["period_ns"] for k in sorted(got["runs"])]
    if not runs:
        return [f"{label}: no burst run"]
    start, end = got["station_period_ns"]
    bad = []
    for edge, value, ran, want, tolerance, source in (
            ("start", start, runs[0][0], first_ns, 0, "the first stamp - 18 + 1 s"),
            ("end", end, runs[-1][1], last_end_ns, 1000, "the last stamp - 18 + 1 s + (n - 1) / 24000 s")):
        if value != ran:
            bad.append(f"{label} station {edge} {(value - ran) / 1e9:+.6f} s from the "
                       f"{'first' if edge == 'start' else 'last'} run's {edge}")
        if abs(value - want) > tolerance:
            bad.append(f"{label} station {edge} {(value - want) / 1e9:+.6f} s from {source}")
    return bad


def stamp_period(g5: Path) -> tuple[int, int]:
    """Return the first burst's first sample and the last burst's last sample of a cut, ns, from the walk."""
    files = sorted((g5 / str(MAPS["G5"]["ex"])).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
    walked = [b for f in files for b in walk_bursts(f)]
    (first, _d), (last, samples) = walked[0], walked[-1]
    return (first - LEAP + 1) * 10**9, (last - LEAP + 1) * 10**9 + (samples.size - 1) * 10**9 // 24000


def check_bursts(g5: Path) -> list[str]:
    """U3, U4 and U10 for the burst archive G5H. Returns the failures."""
    from mt_io.phoenix.readers.segmented.decimated_segmented_reader import DecimatedSegmentCollection

    bad = []
    survey = survey_for("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
    try:
        path = ingest_site(survey, "G5H", overwrite=True)
    except Exception as exc:
        return [f"G5H ingest failed: {exc}"]
    got = read_bursts_archive(path, "G5H")
    runs = got["runs"]
    expected_ids = [f"sr24000_{k:05d}" for k in range(1, 25)]
    if sorted(runs) != expected_ids:
        bad.append(f"G5H runs {len(runs)} ({sorted(runs)[:2]}..), expected 24 sr24000_00001..00024")
    if any(r["rate"] != 24000.0 for r in runs.values()):
        bad.append(f"G5H rates {sorted({r['rate'] for r in runs.values()})}")
    bad += check_station_period(got, "G5H", *stamp_period(g5))
    line = "phoenix_stamp_correction_s: 1.0 s added to every time stamp"
    if line not in got["station_comment"]:
        bad.append("G5H station comment lacks the stamp line")
    for comp, folder in MAPS["G5"].items():
        files = sorted((g5 / str(folder)).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
        walked = [b for f in files for b in walk_bursts(f)]
        mtio = []
        for f in files:
            mtio += [np.asarray(c.ts) for c in DecimatedSegmentCollection(f).to_channel_ts()]
        if len(walked) != 24 or len(mtio) != 24:
            bad.append(f"{comp}: walk {len(walked)}, mt-io {len(mtio)} bursts; expected 24")
        for k, run_id in enumerate(expected_ids):
            run = runs.get(run_id)
            if run is None or k >= len(walked):
                continue
            stamp, samples = walked[k]
            if not np.array_equal(run["data"].get(comp, np.array([])).astype("<f4"), samples):
                bad.append(f"{run_id} {comp}: samples differ from the walk")
            if k < len(mtio) and not np.array_equal(run["data"].get(comp, np.array([])), mtio[k]):
                bad.append(f"{run_id} {comp}: samples differ from mt-io's to_channel_ts()[{k}]")
            want = (stamp - LEAP + 1) * 10**9
            if run["start_ns"] != want:
                bad.append(f"{run_id}: first sample {(run['start_ns'] - want) / 1e9:+.3f} s from its stamp - 18 + 1 s")
            if line not in run["run_comment"] or any(line not in c for c in run["channel_comments"].values()):
                bad.append(f"{run_id}: the stamp line is missing from a comment")
    return bad


class _LaterReader:
    """An mt-io Phoenix reader whose `segment_start_time` is later by a set number of seconds."""

    def __init__(self, inner, delta_s: float):
        self._inner, self._delta_s = inner, delta_s

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def segment_start_time(self):
        return self._inner.segment_start_time + self._delta_s


class _LaterSegment:
    """An mt-io Phoenix segment whose `gps_time_stamp` is later by a set number of seconds."""

    def __init__(self, inner, delta_s: float):
        self._inner, self._delta_s = inner, delta_s

    def __getattr__(self, name):
        return getattr(self._inner, name)

    @property
    def gps_time_stamp(self):
        return self._inner.gps_time_stamp + self._delta_s


def mtio_dates_later(delta_s: float):
    """Make mt-io date every Phoenix file and burst `delta_s` later; returns the function that undoes it."""
    import mt_io.phoenix.read as mtio_read
    from mt_io.phoenix.readers.segmented.decimated_segmented_reader import DecimatedSegmentCollection

    kept_open, kept_segments = mtio_read.open_phoenix, DecimatedSegmentCollection.read_segments

    def open_later(*args, **kwargs):
        return _LaterReader(kept_open(*args, **kwargs), delta_s)

    def segments_later(self, *args, **kwargs):
        return [_LaterSegment(s, delta_s) for s in kept_segments(self, *args, **kwargs)]

    mtio_read.open_phoenix = open_later
    DecimatedSegmentCollection.read_segments = segments_later

    def undo():
        mtio_read.open_phoenix = kept_open
        DecimatedSegmentCollection.read_segments = kept_segments

    return undo


def check_stamp_guard(g5: Path) -> list[str]:
    """U12: the version-2 guard with mt-io dating 1 s and 0.5 s later. Returns the failures."""
    bad = []
    line = "phoenix_stamp_correction_s: 0.0 s added"
    survey = survey_for("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
    undo = mtio_dates_later(1.0)
    try:
        run = read_runs(g5, "G5")[0]
        bursts = read_bursts_archive(ingest_site(survey, "G5H", overwrite=True), "G5H")
    finally:
        undo()
    want = (rec_id(g5) - LEAP + 1 + 1) * 10**9
    if run["start_ns"] != want:
        bad.append(f"G5 +1 s: first sample {(run['start_ns'] - want) / 1e9:+.3f} s from the recording id - 18 + 1 + 1 s")
    if (line not in run["run_comment"] or line not in run["station_comment"]
            or any(line not in c for c in run["channel_comments"].values())):
        bad.append(f"G5 +1 s: a comment lacks {line!r}: {run['run_comment'][-160:]}")
    files = sorted((g5 / str(MAPS["G5"]["ex"])).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
    stamps = [stamp for f in files for stamp, _d in walk_bursts(f)]
    runs = [bursts["runs"][k] for k in sorted(bursts["runs"])]
    if len(runs) != len(stamps):
        bad.append(f"G5H +1 s: {len(runs)} runs for {len(stamps)} bursts")
    for k, (stamp, burst) in enumerate(zip(stamps, runs)):
        want = (stamp - LEAP + 1) * 10**9
        if burst["start_ns"] != want:
            bad.append(f"G5H +1 s burst {k + 1}: first sample {(burst['start_ns'] - want) / 1e9:+.3f} s from its "
                       f"stamp - 18 + 1 s")
            break
    bad += check_station_period(bursts, "G5H +1 s", *stamp_period(g5))
    if line not in bursts["station_comment"] or any(
            line not in r["run_comment"] or any(line not in c for c in r["channel_comments"].values()) for r in runs):
        bad.append(f"G5H +1 s: a comment lacks {line!r}")
    undo = mtio_dates_later(0.5)
    try:
        for site, ext in (("G5", ".td_150"), ("G5H", ".td_24k")):
            try:
                ingest_site(survey, site, overwrite=True)
                bad.append(f"{site} +0.5 s: accepted")
            except ValueError as exc:
                if ext not in str(exc):
                    bad.append(f"{site} +0.5 s: the error names no {ext} file: {str(exc)[:160]}")
    finally:
        undo()
    return bad


def check_station_lists() -> list[str]:
    """U11: the station's recorded channels and run list in the G5 and G5H archives. Returns the failures."""
    import json as _json

    import h5py

    bad = []
    survey = survey_for("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
    for site in ("G5", "G5H"):
        path = ingest_site(survey, site, overwrite=True)
        with h5py.File(path, "r") as f:
            group = f[f"Experiment/Surveys/PHOENIX_TEST/Stations/{site}"]
            recorded = _json.loads(group.attrs["channels_recorded"])
            run_list = _json.loads(group.attrs["run_list"])
            runs = sorted(k for k in group if k.startswith("sr"))
        tags = sorted(set(recorded) & {"e1", "e2", "h1", "h2", "h3"})
        if tags:
            bad.append(f"{site}: channels_recorded {recorded} names mt-io's {tags}")
        if sorted(run_list) != runs:
            bad.append(f"{site}: run_list holds {sorted(set(run_list) - set(runs))} the station does not")
    return bad


def check_rate() -> list[str]:
    """U10: G5 declared at 1000 Hz must be refused."""
    text = refusal("G5", {}, rate=1000.0)
    return [] if text != "ACCEPTED" and "1000 Hz" in text else [f"G5 at 1000 Hz: {text[:120]}"]


def make_cut_burst() -> Path:
    """Return G5C: a cut of G5 whose last `.td_24k` file per channel folder ends CUT_SAMPLES into its last burst."""
    cut = make_cut("G5", "G5C", n150=1, n24=2)
    for folder in sorted(p for p in cut.iterdir() if p.is_dir()):
        last = max(folder.glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
        n_last = walk_bursts(last)[-1][1].size
        with open(last, "r+b") as handle:
            handle.truncate(last.stat().st_size - 4 * (n_last - CUT_SAMPLES))
    return cut


def check_cut_burst(g5c: Path) -> list[str]:
    """U13: G5CH from a recording whose last burst file is cut inside a burst. Returns the failures."""
    survey = survey_for("G5C", {}, extra={"G5CH": {"bursts_of": "G5C", "sample_rate": 24000}})
    files = sorted((g5c / str(MAPS["G5"]["ex"])).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
    tail = files[-1].stat().st_size - 128 - sum(32 + 4 * d.size for _s, d in walk_bursts(files[-1]))
    if tail != 32 + 4 * CUT_SAMPLES:
        return [f"G5C premise: {files[-1].name} holds {tail} bytes after its whole bursts, expected "
                f"{32 + 4 * CUT_SAMPLES}"]
    messages = []
    sink = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    try:
        path = ingest_site(survey, "G5CH", overwrite=True)
    except Exception as exc:
        return [f"G5CH refused: {str(exc)[:200]}"]
    finally:
        logger.remove(sink)
    got = read_bursts_archive(path, "G5CH")
    runs = [got["runs"][k] for k in sorted(got["runs"])]
    bad = []
    for comp, folder in MAPS["G5"].items():
        files = sorted((g5c / str(folder)).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
        walked = [b for f in files for b in walk_bursts(f)]
        if len(runs) != len(walked) or len(walked) != 23:
            bad.append(f"G5CH {comp}: {len(runs)} runs, {len(walked)} whole bursts walked; expected 23")
        for k, (run, (_stamp, samples)) in enumerate(zip(runs, walked)):
            if not np.array_equal(run["data"].get(comp, np.array([])).astype("<f4"), samples):
                bad.append(f"G5CH run {k + 1} {comp}: samples differ from the walk")
                break
    if not any(files[-1].name in m and "cut short" in m for m in messages):
        bad.append(f"G5CH: no warning names {files[-1].name} as cut short")
    return bad


def check_partial_removed(g5c: Path) -> list[str]:
    """U13: a failure forced inside `_ingest_bursts` after five runs leaves no archive. Returns the failures."""
    survey = survey_for("G5C", {}, extra={"G5CH": {"bursts_of": "G5C", "sample_rate": 24000}})
    path = ingest.default_archive_path(survey, "G5CH")
    calls = [0]
    kept = phoenix.stamp_correction

    def failing(*args):
        calls[0] += 1
        if calls[0] > 5 * len(MAPS["G5"]):
            raise RuntimeError("forced failure inside _ingest_bursts")
        return kept(*args)

    phoenix.stamp_correction = failing
    try:
        ingest_site(survey, "G5CH", overwrite=True)
        return ["the forced failure did not propagate"]
    except RuntimeError:
        pass
    finally:
        phoenix.stamp_correction = kept
    bad = []
    if calls[0] <= 5 * len(MAPS["G5"]):
        bad.append(f"premise: the failure came after {calls[0]} stamp checks, before five runs")
    left = sorted(p.name for p in path.parent.glob("G5CH*"))
    if left:
        bad.append(f"left after the forced failure: {left} ({path.stat().st_size if path.exists() else 0} bytes)")
    return bad


def check_burst_clock(g5: Path) -> list[str]:
    """U14: the burst site's clock under a recorded site declaring -0.1148 s. Returns the failures."""
    offset, own = -0.1148, 0.05
    bad = []
    run = read_runs(g5, "G5", {"clock_offset_s": offset})[0]
    want = (rec_id(g5) - LEAP + 1 + 1) * 10**9 + round(offset * 1e9)
    if abs(run["start_ns"] - want) > 1000:
        bad.append(f"G5 at {offset} s: first sample {(run['start_ns'] - want) / 1e9:+.6f} s from the recording id "
                   f"- 18 + 1 + 1 {offset:+} s")
    files = sorted((g5 / str(MAPS["G5"]["ex"])).glob("*.td_24k"), key=lambda p: int(p.stem.split("_")[3], 16))
    stamps = [stamp for f in files for stamp, _d in walk_bursts(f)]
    for label, extra, shift_ns, tolerance in (("not declared", {}, 0, 0),
                                              ("declaring 0.05", {"clock_offset_s": own}, round(own * 1e9), 1000)):
        survey = survey_for("G5", {"clock_offset_s": offset},
                            extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000, **extra}})
        try:
            got = read_bursts_archive(ingest_site(survey, "G5H", overwrite=True), "G5H")
        except Exception as exc:
            bad.append(f"G5H {label}: the ingest failed: {str(exc)[:160]}")
            continue
        runs = [got["runs"][k] for k in sorted(got["runs"])]
        if len(runs) != len(stamps):
            bad.append(f"G5H {label}: {len(runs)} runs for {len(stamps)} bursts")
        for k, (burst, stamp) in enumerate(zip(runs, stamps)):
            want = (stamp - LEAP + 1) * 10**9 + shift_ns
            if abs(burst["start_ns"] - want) > tolerance:
                bad.append(f"G5H {label} burst {k + 1}: first sample {(burst['start_ns'] - want) / 1e9:+.6f} s from its "
                           f"stamp - 18 + 1 s{f' + {own} s' if shift_ns else ''}")
                break
        noted = [any("clock_offset_s:" in c for c in (r["run_comment"], *r["channel_comments"].values()))
                 for r in runs]
        if shift_ns and not all(noted):
            bad.append(f"G5H {label}: {noted.count(False)} runs lack the clock_offset_s line")
        if not shift_ns and any(noted):
            bad.append(f"G5H {label}: {noted.count(True)} runs carry a clock_offset_s line")
    return bad


GAP_CASES = {"G5Z": ("trailing_empty", [[1, 2, 3]]), "G5M": ("missing", [[1], [3, 4]]),
             "G5E": ("empty", [[1], [3, 4]])}
PLANS_FIXTURE = REPO / "tests" / "fixtures" / "phoenix_plans" / "ptest_plans.json"
# 0.9 x 5 V / the header's total circuitry gain: E at gain 2, H at gain 4 (G5's headers)
G5_RAILS = {"ex": 2.25, "ey": 2.25, "hx": 1.125, "hy": 1.125}


def make_gap_cut(name: str) -> Path:
    """Copy G5's first `.td_150` files (no bursts) and apply a gap case of `GAP_CASES`.

    Returns:
        Path: The cut's folder.
    """
    edit = GAP_CASES[name][0]
    cut = make_cut("G5", name, n150=3 if edit == "trailing_empty" else 4, n24=0)
    if edit == "trailing_empty":
        for folder in sorted(p for p in cut.iterdir() if p.is_dir()):
            receiver, rec_hex, channel, _seq = next(folder.glob("*.td_150")).stem.split("_")
            (folder / f"{receiver}_{rec_hex}_{channel}_{4:08X}.td_150").write_bytes(b"")
    else:
        second = next((cut / str(MAPS["G5"]["hx"])).glob("*_00000002.td_150"))
        if edit == "missing":
            second.unlink()
        else:
            second.write_bytes(b"")
    return cut


def check_gaps(cuts: dict) -> list[str]:
    """U15: ingest each gap cut and compare its runs with the folders' files. Returns the failures."""
    bad = []
    for site, cut in cuts.items():
        edit, want = GAP_CASES[site]
        warnings: list[str] = []
        sink = logger.add(lambda m: warnings.append(str(m)), level="WARNING")
        try:
            runs = read_runs(cut, site)
        except Exception as exc:  # the code before the fix refuses: a failure of the check, not a crash
            bad.append(f"{site} ({edit}): {type(exc).__name__}: {str(exc)[:160]}")
            continue
        finally:
            logger.remove(sink)
        got = [r["sequences"] for r in runs]
        if got != want:
            bad.append(f"{site} ({edit}): runs {got}, expected {want}")
            continue
        rid = rec_id(cut)
        for k, run in enumerate(runs):
            lengths = {comp: data.size for comp, data in run["data"].items()}
            if len(set(lengths.values())) != 1 or set(lengths) != set(MAPS["G5"]):
                bad.append(f"{site} run {k + 1}: channel lengths {lengths}")
            for comp, folder in MAPS["G5"].items():
                if comp in run["data"] and not np.array_equal(run["data"][comp].astype("<f4"),
                                                              file_bytes(cut, folder, run["sequences"])):
                    bad.append(f"{site} run {k + 1} {comp}: not folder {folder}'s files {run['sequences']}")
            first = run["sequences"][0]
            want_ns = (rid - LEAP + (1 if first == 1 else 360 * (first - 1)) + 1) * 10**9
            off = {comp: (ns - want_ns) / 1e9 for comp, ns in run["starts"].items() if ns != want_ns}
            if off:
                bad.append(f"{site} run {k + 1}: channel starts off sequence {first}'s time by {off} s")
            gap = [p for p in run["run_comment"].split("; ") if p.startswith("phoenix_gap:")]
            if len(want) > 1 and k == 1:
                if not (len(gap) == 1 and "sequence 2" in gap[0] and f"folder {MAPS['G5']['hx']}" in gap[0]
                        and "360 s" in gap[0]):
                    bad.append(f"{site} run 2: gap lines {gap}, expected one naming sequence 2, folder "
                               f"{MAPS['G5']['hx']} and 360 s")
            elif gap:
                bad.append(f"{site} run {k + 1}: unexpected gap line {gap}")
            rails = {r["channel"]: r.get("rail_level") for r in parse_level_note(run["run_comment"])}
            if any(rails.get(c) is None or abs(rails[c] - v) > 1e-9 for c, v in G5_RAILS.items()):
                bad.append(f"{site} run {k + 1} (U17): dc level rails {rails}, expected {G5_RAILS}")
            dotted = [p.split(":", 1)[0] for p in run["run_comment"].split(";")
                      if ":" in p and "." in p.split(":", 1)[0]]
            if dotted:
                bad.append(f"{site} run {k + 1} (U17): run-comment keys with a dot {dotted}")
        empties = ([f"_{f}_00000004.td_150" for f in MAPS["G5"].values()] if edit == "trailing_empty" else
                   [f"_{MAPS['G5']['hx']}_00000002.td_150"] if edit == "empty" else [])
        named = [w for w in warnings if "0 bytes" in w]
        if len(named) != len(empties) or not all(any(e in w for w in named) for e in empties):
            bad.append(f"{site} ({edit}): warnings naming empty files {named}, expected one each for {empties}")
    return bad


def check_plans_unchanged() -> list[str]:
    """U16: the plans of the test folder's recordings equal the fixture of 8a72107. Returns the failures."""
    import json

    fixture = json.loads(PLANS_FIXTURE.read_text(encoding="utf-8"))
    source, bad = Path(fixture["source"]), []
    for key, want in fixture["plans"].items():
        rel, suffix = key.rsplit(" ", 1)
        rec = phoenix.open_recording(source / rel)
        try:
            runs = phoenix.plan_runs(phoenix.recording_files(rec, suffix), {".td_150": 150.0, ".td_30": 30.0}[suffix])
        except ValueError as exc:
            got = {"error": str(exc)}
        else:
            got = {"runs": [{"sequences": r.sequences, "start_s": r.start_s, "n": r.n,
                             "folder_sequences": sorted({tuple(f.sequence for f in v) == tuple(r.sequences)
                                                         for v in r.files.values()}),
                             "folders": sorted(r.files)} for r in runs]}
            notes = [n for r in runs for n in getattr(r, "notes", [])]
            if notes:
                bad.append(f"{key}: gap notes {notes}")
        if got != want:
            bad.append(f"{key}: plan differs from {fixture['code']}'s ({len(got.get('runs', []))} runs against "
                       f"{len(want.get('runs', []))})")
    return bad


def band_passed(x: np.ndarray, rate: float = 150.0, band: tuple = (0.5, 10.0)) -> np.ndarray:
    """Return a series band-passed by zeroing its spectrum outside `band`, mean removed."""
    f = np.fft.rfftfreq(x.size, 1 / rate)
    spec = np.fft.rfft(np.asarray(x, dtype=float) - np.mean(x))
    spec[(f < band[0]) | (f > band[1])] = 0
    return np.fft.irfft(spec, x.size)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    """Return the zero-lag correlation coefficient of two series, both band-passed (`band_passed`)."""
    a, b = band_passed(a), band_passed(b)
    return float(np.sum(a * b) / np.sqrt(np.sum(a * a) * np.sum(b * b)))


def calibrated(run, library: bool = False) -> dict:
    """Return {comp: samples} of a RunTS calibrated through its archive chains.

    By default each channel's spectrum is divided by its chain's complex
    response, as aurora calibrates its STFT; with `library`, mt_timeseries'
    `RunTS.calibrate` is used instead (it is not a plain divide on G5's E,
    which correlates +0.80 and -0.85 with the divide over 0.5-10 Hz, so it
    is used on H only).
    """
    if library:
        out = run.calibrate()
        return {comp: np.asarray(out.dataset[comp].data, dtype=float) for comp in out.dataset.data_vars}
    out = {}
    for comp in run.dataset.data_vars:
        x = np.asarray(run.dataset[comp].data, dtype=float)
        f = np.fft.rfftfreq(x.size, 1 / float(run.sample_rate))
        response = getattr(run, comp).channel_response.complex_response(np.where(f > 0, f, f[1]))
        out[comp] = np.fft.irfft(np.fft.rfft(x - x.mean()) / response, x.size)
    return out


def check_polarity(g5: Path) -> list[str]:
    """U18: the H polarity stage on hx and hy (not E), its response, the calibrated sign, flip_h and swap_h."""
    from mt_metadata.timeseries.filters import ChannelResponse

    bad = []
    name = phoenix.H_POLARITY
    plain = read_runs(g5, "G5", keep_run=True)[0]
    filters = plain["filters"]
    for comp in ("hx", "hy", "ex", "ey"):
        names = plain["chains"][comp]
        held = names.count(name)
        if comp.startswith("h"):
            stage = filters.get(name)
            if held != 1 or stage is None or type(stage).__name__ != "CoefficientFilter" or float(stage.gain) != -1.0:
                bad.append(f"{comp}: {held} {name} stage(s) in {names}, "
                           f"gain {getattr(stage, 'gain', None)}")
                continue
            if f"{name} -1" not in plain["channel_comments"][comp]:
                bad.append(f"{comp}: comment lacks '{name} -1'")
        elif held or name in plain["channel_comments"][comp]:
            bad.append(f"{comp}: holds {name} ({names})")
            continue
        chain = [filters[n] for n in names]
        total = ChannelResponse(filters_list=chain)
        z = complex(total.complex_response(np.array([1.0]), filters_list=chain)[0])
        phase = float(np.degrees(np.angle(z)))
        if comp.startswith("h"):
            rest = [f for f in chain if f.name != name]
            unsigned = complex(ChannelResponse(filters_list=rest).complex_response(np.array([1.0]),
                                                                                  filters_list=rest)[0])
            if abs(z / unsigned + 1.0) > 1e-12:
                bad.append(f"{comp}: chain / chain without the stage = {z / unsigned:.6g}, expected -1")
            if abs(abs(phase) - 180.0) > 10.0:
                bad.append(f"{comp}: total phase at 1 Hz {phase:+.2f} deg, expected 180 +- 10")
        elif abs(phase) > 1.0:
            bad.append(f"{comp}: total phase at 1 Hz {phase:+.2f} deg, expected 0 +- 1")
    if not np.array_equal(plain["data"]["hx"].astype("<f4"), file_bytes(g5, MAPS["G5"]["hx"], plain["sequences"])):
        bad.append("hx: stored samples differ from the file bytes")
    cal, lib = calibrated(plain["run"]), calibrated(plain["run"], library=True)
    for comp, want in (("hx", -1), ("hy", -1), ("ex", 1), ("ey", 1)):
        for label, series in (("divided", cal), ("mt_timeseries", lib if comp.startswith("h") else None)):
            if series is None:
                continue
            r = correlation(plain["data"][comp], series[comp])
            if want * r < 0.9:
                bad.append(f"{comp}: stored x calibrated ({label}) r {r:+.4f}, expected "
                           f"{'below -0.9' if want < 0 else 'above +0.9'}")
    flipped = read_runs(g5, "G5", {"flip_h": ["hy"]}, keep_run=True)[0]
    if not np.array_equal(flipped["data"]["hy"].astype("<f4"),
                          -file_bytes(g5, MAPS["G5"]["hy"], flipped["sequences"])):
        bad.append("flip_h hy: stored samples are not minus the file bytes")
    if flipped["chains"]["hy"] != plain["chains"]["hy"]:
        bad.append(f"flip_h hy: chain {flipped['chains']['hy']} against {plain['chains']['hy']}")
    r = correlation(calibrated(flipped["run"])["hy"], cal["hy"])
    if r > -0.99:
        bad.append(f"flip_h hy: calibrated flipped x calibrated plain r {r:+.4f}, expected below -0.99")
    swapped = read_runs(g5, "G5", {"swap_h": True})[0]
    for comp in ("hx", "hy"):
        if swapped["chains"][comp].count(name) != 1:
            bad.append(f"swap_h {comp}: chain {swapped['chains'][comp]}")
    survey = survey_for("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
    path = ingest_site(survey, "G5H", overwrite=True)
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        group = m.get_station("G5H", survey=m.surveys_group.groups_list[0]).get_run("sr24000_00001")
        for comp in ("hx", "hy", "ex"):
            names = [f.name for f in group.get_channel(comp).metadata.filters]
            if names.count(name) != (1 if comp.startswith("h") else 0):
                bad.append(f"G5H {comp}: chain {names}")
    finally:
        m.close_mth5()
    return bad


def check_coil_missing(g5: Path) -> list[str]:
    """U18, no coil table: G5 ingests with [phoenix_h_polarity, phoenix_mv_to_v, curve] on H, units accepted."""
    from mt_metadata.timeseries.filters import ChannelResponse

    kept = phoenix._coil_stage
    phoenix._coil_stage = lambda serial, calibration_dir, start_s=None: (None, None, None)
    try:
        run = read_runs(g5, "G5")[0]
    except Exception as exc:  # noqa: BLE001  (any refusal of the chain is the finding)
        return [f"coil missing: G5 refused: {type(exc).__name__}: {str(exc)[:200]}"]
    finally:
        phoenix._coil_stage = kept
    bad = []
    for comp in ("hx", "hy"):
        names = run["chains"][comp]
        if (len(names) != 3 or names[0] != phoenix.H_POLARITY or names[1] != phoenix.MV_TO_V
                or "lowpass" not in names[2]):
            bad.append(f"coil missing {comp}: chain {names}")
            continue
        if float(run["filters"][names[0]].gain) != -1.0:
            bad.append(f"coil missing {comp}: gain {run['filters'][names[0]].gain}")
        chain = [run["filters"][n] for n in names]
        try:
            total = ChannelResponse(filters_list=chain)
        except Exception as exc:  # noqa: BLE001
            bad.append(f"coil missing {comp}: ChannelResponse refuses the chain: {str(exc)[:200]}")
            continue
        if not str(total.units_out).lower().startswith("v"):
            bad.append(f"coil missing {comp}: units {total.units_in} to {total.units_out}")
    return bad


def nt_polarity_stage():
    """Return the polarity stage labelled nT in, nT out: U18's coil-missing mutation."""
    from mt_metadata.timeseries.filters import CoefficientFilter

    stage = CoefficientFilter()
    stage.name, stage.gain = phoenix.H_POLARITY, phoenix.H_POLARITY_GAIN
    stage.units_in, stage.units_out = "nanoTesla", "nanoTesla"
    return stage


def station_reads(g5: Path, n: int) -> dict:
    """Ingest G5H's first `n` bursts, counting the station getter's and `Station.update_all`'s calls.

    Args:
        g5 (Path): The G5 cut.
        n (int): Bursts to ingest, from the first.

    Returns:
        dict: {"getter": calls, "with_runs": calls made while the station
        held a run, "update_all": calls, "runs": runs in the archive}.
    """
    import h5py
    import mth5.groups.station as station_module
    from mt_metadata.timeseries import Station

    survey = survey_for("G5", {}, extra={"G5H": {"bursts_of": "G5", "sample_rate": 24000}})
    slots = phoenix.burst_slots(phoenix.open_recording(g5))[0]
    end = pd.Timestamp(slots[n].start_s, unit="s") if n < len(slots) else None  # naive UTC, as burst_slots takes it
    counts = {"getter": 0, "with_runs": 0, "update_all": 0}
    getter, update_all = station_module.StationGroup.metadata, Station.update_all

    def counting_getter(self):
        counts["getter"] += 1
        skip = {name.lower() for name in self._default_subgroup_names}
        counts["with_runs"] += any(key.lower() not in skip for key in self.groups_list)
        return getter.fget(self)

    def counting_update_all(self):
        counts["update_all"] += 1
        return update_all(self)

    station_module.StationGroup.metadata = property(counting_getter, getter.fset)
    Station.update_all = counting_update_all
    try:
        path = ingest_site(survey, "G5H", end=end, overwrite=True)
    finally:
        station_module.StationGroup.metadata, Station.update_all = getter, update_all
    with h5py.File(path, "r") as f:
        counts["runs"] = sum(1 for k in f["Experiment/Surveys/PHOENIX_TEST/Stations/G5H"] if k.startswith("sr"))
    return counts


def check_station_reads(g5: Path) -> list[str]:
    """U19: the station getter's and update_all's calls in G5H ingests of 12 and 24 bursts. Returns the failures."""
    bad = []
    got = {n: station_reads(g5, n) for n in (12, 24)}
    for n, c in got.items():
        if c["runs"] != n:
            bad.append(f"G5H window of {n} bursts holds {c['runs']} runs")
        if c["getter"] > MAX_STATION_READS:
            bad.append(f"{n} runs: {c['getter']} station getter calls, more than {MAX_STATION_READS}")
        if c["with_runs"]:
            bad.append(f"{n} runs: {c['with_runs']} station getter call(s) with the runs present")
    for key in ("getter", "update_all"):
        if got[12][key] != got[24][key]:
            bad.append(f"{key} calls {got[12][key]} at 12 runs, {got[24][key]} at 24 runs")
    return bad


def mutated(target, name: str, value, check, *args) -> list[str]:
    """Run a check with one attribute of a module replaced, and return what it reports."""
    kept = getattr(target, name)
    setattr(target, name, value)
    try:
        return check(*args)
    finally:
        setattr(target, name, kept)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    g5, j1 = make_cut("G5"), make_cut("J1")
    g5t = make_cut("G5", "G5T", truncate=2)
    failures = []

    for cut, site in ((g5, "G5"), (j1, "J1")):
        bad = check_map(cut, site)
        failures += bad
        print(f"  U{1 if site == 'G5' else 2} {site}: {'ok' if not bad else bad}; "
              f"{', '.join(f'{c} folder {f}' for c, f in MAPS[site].items())}")
    swapped = {**phoenix.RENAME, "e1": "ey", "e2": "ex"}
    trip = mutated(phoenix, "RENAME", swapped, check_map, g5, "G5")
    assert trip, "mutation U1 (e1 and e2 swapped) did not trip"
    print(f"  U1 mutation (e1/e2 swapped) tripped: {trip[0]}")

    from mt_io.phoenix.readers.header import Header
    default_map = Header().channel_map

    def default_tags(path):
        rec = kept_open(path)
        rec.tags = {i: default_map[i] for i in rec.tags}
        return rec

    kept_open = phoenix.open_recording
    trip = mutated(phoenix, "open_recording", default_tags, check_map, j1, "J1")
    assert trip, "mutation U2 (mt-io's default map) did not trip"
    print(f"  U2 mutation (mt-io's default channel map) tripped: {trip[0]}")

    bad = check_reader(g5) + check_reader(j1)
    failures += bad
    print(f"  U3 continuous: {'ok' if not bad else bad}: open_phoenix(fn).read() equals the file bytes, "
          f"{len(list(g5.glob('*/*.td_150'))) + len(list(j1.glob('*/*.td_150')))} files")

    for cut, site in ((g5, "G5"), (j1, "J1")):
        bad = check_stamps(cut, site)
        failures += bad
        print(f"  U4 {site}: {'ok' if not bad else bad}: first sample at recording id - 18 + 1 + 1 s, the line "
              f"in run, channel and station comments")
    trip0 = mutated(phoenix, "stamp_correction", lambda *a: 0.0, check_stamps, g5, "G5")
    trip2 = mutated(phoenix, "stamp_correction", lambda *a: 2 * phoenix.STAMP_CORRECTION_S, check_stamps, g5, "G5")
    assert any("-1.000 s" in t for t in trip0), trip0
    assert any("+1.000 s" in t for t in trip2), trip2
    print(f"  U4 mutations tripped: dropped {trip0[0].split('(')[-1]} applied twice {trip2[0].split('(')[-1]}")

    bad = check_coils(g5, j1)
    failures += bad
    print(f"  U5: {'ok' if not bad else bad}: G5 hx phoenix_coil_53508 equals its scal table; J1 54870 with the "
          f"self-report warning, phoenix_coil_53674 with coil_hx")

    def recmeta_serial(rec, tag, md):
        return str(rec.chan(tag, rec.recmeta).get("serial"))

    trip = mutated(phoenix, "_metadata_serial", recmeta_serial, check_coils, g5, j1)
    assert any("54047" in t or "phoenix_coil_54047" in t for t in trip), trip
    print(f"  U5 mutation (serial from recmeta.json) tripped: {trip[0][:100]}")

    bad = check_units(g5)
    failures += bad
    print(f"  U6: {'ok' if not bad else bad}: |chain|/|rx| = L x 1e-6 (ex, ey) and |coil| x 1e-3 (hx); units "
          f"mV/km or nT -> V; calibrate quiet")
    def keep_v_to_mv(chain, name):
        stage = next(f for f in chain if f.name == "v_to_mv").copy()
        stage.units_in, stage.units_out = "milliVolt", "Volt"  # labels that fit the chain, gain 1000 kept
        return stage, False

    trip = mutated(phoenix, "_units_stage", keep_v_to_mv, check_units, g5)
    assert trip and all("e+06" in t or "1.00e+06" in t for t in trip[:3]), trip
    print(f"  U6 mutation (mt-io's v_to_mv kept) tripped: {trip[0][:110]}")

    bad = check_dipoles(g5)
    failures += bad
    print(f"  U7: {'ok' if not bad else bad}: G5 ey 85 m from empower_recmeta.json; 100 m from survey.yaml with "
          f"empower 85 noted")

    def recmeta_dipole(rec, tag, md):
        theirs = rec.chan(tag, rec.recmeta)
        return float(theirs["length1"]) + float(theirs["length2"])

    trip = mutated(phoenix, "_metadata_dipole", recmeta_dipole, check_dipoles, g5)
    assert trip, "mutation U7 (dipole from recmeta.json) did not trip"
    print(f"  U7 mutation (dipole from recmeta.json) tripped: {trip[0][:100]}")

    bad = check_split(g5t)
    failures += bad
    print(f"  U8 G5T: {'ok' if not bad else bad}: runs [1, 2] and [3], run 2 at the recording id - 18 + 721 s")
    trip = mutated(phoenix, "_JOIN_TOLERANCE_SAMPLES", np.inf, check_split, g5t)
    assert trip, "mutation U8 (join whatever the starts) did not trip"
    print(f"  U8 mutation (join by sequence) tripped: {trip[0]}")

    bad = check_keys(g5)
    failures += bad
    print(f"  U9: {'ok' if not bad else bad}: model, h_scale, serial 10134 and dipole_length_ex on G5H refused; "
          f"a td_2400 file noted in the run comment")
    trip = mutated(ingest, "_NOT_PHOENIX_KEYS", (), check_keys, g5)
    assert any(t.startswith("h_scale") for t in trip), trip
    print(f"  U9 mutation (h_scale allowed) tripped: {next(t for t in trip if t.startswith('h_scale'))}")
    bad = check_rate()
    failures += bad
    print(f"  U10: {'ok' if not bad else bad}: G5 declared at 1000 Hz refused")
    trip = mutated(phoenix, "_check_rates", lambda files, rate: None, check_rate)
    assert trip, "mutation U10 (no rate check) did not trip"
    print(f"  U10 mutation (no rate check) tripped: {trip[0]}")

    bad = check_station_lists()
    failures += bad
    print(f"  U11: {'ok' if not bad else bad}: G5 and G5H stations list ex ey hx hy and their own runs only")

    def keep_mtio_record(station_md, site_name):
        station_md.id = site_name
        return station_md

    kept_run = phoenix.run_record
    phoenix.run_record = lambda run_md: run_md
    try:
        trip = mutated(phoenix, "station_record", keep_mtio_record, check_station_lists)
    finally:
        phoenix.run_record = kept_run
    assert trip, "mutation U11 (mt-io's station record kept) did not trip"
    print(f"  U11 mutation (mt-io's station record kept) tripped: {trip[0][:100]}")

    bad = check_bursts(g5)
    failures += bad
    print(f"  U3/U4/U10 bursts: {'ok' if not bad[:3] else bad[:3]}: G5H 24 runs sr24000_00001-00024 at 24000 Hz, "
          f"each equal to the sub-header walk and to mt-io's to_channel_ts()[k], first sample at stamp - 18 + 1 s, "
          f"the station from the first run's start to the last run's end")

    def first_burst_only(path):
        from mt_io.phoenix.read import read_phoenix
        ch = read_phoenix(path)
        return [(phoenix._seconds(ch.start), np.asarray(ch.ts))]

    trip = mutated(phoenix, "_read_bursts", first_burst_only, check_bursts, g5)
    assert trip, "mutation U3 (read_phoenix, first burst only) did not trip"
    print(f"  U3 mutation (read_phoenix: first burst only) tripped: {trip[0][:110]}")
    trip0 = mutated(phoenix, "stamp_correction", lambda *a: 0.0, check_bursts, g5)
    trip2 = mutated(phoenix, "stamp_correction", lambda *a: 2 * phoenix.STAMP_CORRECTION_S, check_bursts, g5)
    assert any("-1.000 s" in t for t in trip0) and any("+1.000 s" in t for t in trip2), (trip0[:2], trip2[:2])
    assert trip0[0].startswith("G5H station start -1.000000 s"), trip0[:2]
    assert trip2[0].startswith("G5H station start +1.000000 s"), trip2[:2]
    print(f"  U4 burst mutations tripped: dropped ({trip0[0]}), twice ({trip2[0]})")

    bad = check_stamp_guard(g5)
    failures += bad
    print(f"  U12: {'ok' if not bad else bad}: mt-io 1 s later gives 0.0 s added and the same GPS starts for G5 and "
          f"G5H and the same G5H station period; mt-io 0.5 s later refused, naming the file")

    def by_version(reader_start_s, expected_s, version, name):
        return phoenix.STAMP_CORRECTION_S if version < phoenix.STAMP_CORRECTED_BELOW else 0.0

    trip = mutated(phoenix, "stamp_correction", by_version, check_stamp_guard, g5)
    late = [t for t in trip if "+1 s" in t and "+1.000 s from" in t]
    assert any(t.startswith("G5 +1 s") for t in late) and any(t.startswith("G5H +1 s") for t in late), trip
    station = [t for t in trip if t.startswith("G5H +1 s station start +1.000000 s")]
    assert station, trip
    print(f"  U12 mutation (correction by version alone) tripped: {late[0][:90]}; {late[-1][:90]}; {station[0]}")

    g5c = make_cut_burst()
    bad = check_cut_burst(g5c)
    failures += bad
    print(f"  U13 cut burst: {'ok' if not bad else bad}: G5CH 23 runs, the cut burst ({CUT_SAMPLES} samples) left out "
          f"with a warning, every run equal to the walk")
    if not bad:
        trip = mutated(phoenix, "cut_burst_samples", lambda *a: None, check_cut_burst, g5c)
        assert trip, "mutation U13 (mt-io's cut burst compared again) did not trip"
        print(f"  U13 mutation (mt-io's cut burst compared again) tripped: {trip[0][:120]}")
    removed = check_partial_removed(g5c)
    failures += removed
    print(f"  U13 forced failure: {'ok' if not removed else removed}: raised after five runs, no G5CH file left")
    if not removed:
        trip = mutated(ingest, "_remove_partial_archive", lambda *a: None, check_partial_removed, g5c)
        assert trip, "mutation U13 (the partial archive kept) did not trip"
        print(f"  U13 mutation (the partial archive kept) tripped: {trip[0][:120]}")

    bad = check_burst_clock(g5)
    failures += bad
    print(f"  U14: {'ok' if not bad else bad}: G5 at -0.1148 s starts at the recording id - 18 + 1 + 1 - 0.1148 s; "
          f"G5H not declaring starts at each stamp - 18 + 1 s with no clock_offset_s line, G5H declaring 0.05 at "
          f"+0.05 s with the line")
    import mt_workbench.survey as survey_module
    kept_burst_site = survey_module.Survey._burst_site

    def inheriting(self, name):
        config = kept_burst_site(self, name)
        config.clock_offset_s = self.site(config.bursts_of).clock_offset_s
        return config

    trip = mutated(survey_module.Survey, "_burst_site", inheriting, check_burst_clock, g5)
    assert any("not declared burst 1: first sample -0.114800 s" in t for t in trip), trip
    print(f"  U14 mutation (the recorded site's offset copied) tripped: {trip[0][:120]}")

    gap_cuts = {site: make_gap_cut(site) for site in GAP_CASES}
    bad = check_gaps(gap_cuts)
    failures += bad
    print(f"  U15 gaps: {'ok' if not bad else bad}: G5Z one run 1-3, the four empty files named; G5M and G5E runs "
          f"1 and 3-4, channels equal to their folders' files, run 2 at sequence 3's time in every channel, the "
          f"phoenix_gap line (sequence 2, folder {MAPS['G5']['hx']}, 360 s)")
    if not bad:
        trip = mutated(phoenix, "_aligned_files", lambda files: (files, []), check_gaps, {"G5M": gap_cuts["G5M"]})
        assert trip, "mutation U15 (each folder's own files) did not trip"
        print(f"  U15 mutation (each folder's own files) tripped: {trip[0][:120]}")
    bad = check_plans_unchanged()
    failures += bad
    print(f"  U16 plans: {'ok' if not bad else bad[:3]}: the 25 test-folder recordings plan as on 8a72107 "
          f"(sequences, first sample, samples, folders), no gap note")
    if not bad:
        trip = mutated(phoenix, "_JOIN_TOLERANCE_SAMPLES", -1.0, check_plans_unchanged)
        assert trip, "mutation U16 (every file its own run) did not trip"
        print(f"  U16 mutation (every file its own run) tripped: {trip[0][:120]}")

    bad = check_polarity(g5)
    failures += bad
    print(f"  U18 polarity: {'ok' if not bad else bad}: {phoenix.H_POLARITY} (gain -1) once on hx and hy, not on "
          f"ex and ey, and on G5H; 1 Hz phase H 180 +- 10, E 0 +- 1; stored x calibrated H below -0.9, E above "
          f"+0.9; flip_h hy still flips, swap_h keeps one stage per channel")
    if not bad:
        trip = mutated(phoenix, "H_POLARITY_GAIN", 1.0, check_polarity, g5)
        assert any("gain 1.0" in t for t in trip) and any("below -0.9" in t for t in trip), trip
        print(f"  U18 mutation (gain +1) tripped: {trip[0][:120]}")
        trip = mutated(phoenix, "_h_polarity_stage", lambda: None, check_polarity, g5)
        assert any("stage(s)" in t for t in trip) and any("below -0.9" in t for t in trip), trip
        print(f"  U18 mutation (no stage) tripped: {trip[0][:120]}")

    bad = check_coil_missing(g5)
    failures += bad
    print(f"  U18 coil missing: {'ok' if not bad else bad}: hx and hy [{phoenix.H_POLARITY} (gain -1), "
          f"{phoenix.MV_TO_V}, receiver curve], the units accepted by ChannelResponse")
    if not bad:
        trip = mutated(phoenix, "_h_polarity_stage", nt_polarity_stage, check_coil_missing, g5)
        assert trip and any("refuse" in t for t in trip), trip
        print(f"  U18 coil-missing mutation (an nT-to-nT stage first) tripped: {trip[0][:160]}")

    bad = check_station_reads(g5)
    failures += bad
    print(f"  U19 station reads: {'ok' if not bad else bad}: G5H of 12 and 24 bursts, the station getter called "
          f"at most {MAX_STATION_READS} times and never with a run present, update_all as often for both")
    if not bad:
        from mth5.groups.station import StationGroup
        kept_add_run = StationGroup.add_run

        def reading_add_run(self, *args, **kwargs):
            run_group = kept_add_run(self, *args, **kwargs)
            _ = self.metadata  # a station read per run
            return run_group

        trip = mutated(StationGroup, "add_run", reading_add_run, check_station_reads, g5)
        assert any(t.startswith("getter calls") for t in trip), trip
        print(f"  U19 mutation (a station read per run) tripped: {trip[0][:120]}")
        trip = mutated(ingest, "_write_group_metadata", lambda group, metadata: group.write_metadata(),
                       check_station_reads, g5)
        assert any("with the runs present" in t for t in trip) and any(t.startswith("update_all") for t in trip), trip
        print(f"  U19 mutation (the station written by mth5's write_metadata) tripped: {trip[0][:120]}")

    if failures:
        print("\nFAIL  ingest_phoenix_unit")
        for line in failures:
            print(f"  {line}")
        raise SystemExit(1)
    shutil.rmtree(DATA)
    print("\nPASS  ingest_phoenix_unit")


if __name__ == "__main__":
    main()
