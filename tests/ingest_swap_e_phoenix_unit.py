# -*- coding: utf-8 -*-
"""
Unit test for `swap_e` on a Phoenix site (mt_workbench.phoenix.component_of, mt_workbench.ingest)

Two cuts of real MTU-8A recordings are copied, read only, into scratch in
the receiver's folder layout (the JSON files, backend.log and config.json
and the first files of every channel folder; folders 0 E1, 2 H2, 3 H1 and
7 E2 on both): J2, the first `.td_150` file of KD-J2's 28 Apr 2021
recording (receiver 10135, raw_extracted/KD-J2 of the Kalkaroo
workspace, whose ex and ey lines were connected to each other's inputs),
and G5, the first `.td_150` and first `.td_24k` file of the Phoenix test
folder's G5 (receiver 10133, empower dipoles E1 100 m and E2 85 m, so the
dipole that goes with an input can be told apart). Each cut is a site of a
scratch survey and is ingested with `ingest_site`, with and without
`swap_e: true`; G5H (`bursts_of: G5`) is the burst path. The archives are
read back with mth5 and compared with the file bytes read here with numpy
and with the metadata files read here with json, never through the reader
under test. During every ingest `phoenix.input_range_v` is replaced so that
folder 7's files give 5 V and folder 0's 1 V (the receiver gives 2.5 V on
both E inputs at these sites), so that the rail that goes with an input can
be told apart.

Usage:
    python tests/ingest_swap_e_phoenix_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - P1: with `swap_e: true`, J2's ex is not folder 7's samples
    (`np.fromfile(file, "<f4", offset=128)`) sample for sample and ey
    folder 0's, or hx and hy are not folders 3 and 2;
  - P2: J2's ex chain is not [dipole_52m, phoenix_mv_to_v,
    mtu-8a_rmt05_10135_e2_10000hz_lowpass] and ey's the e1 curve, a chain's
    response at 0.1, 1, 10 and 100 Hz differs by more than 1e-12 relative
    from the response of the same input's chain in the archive without
    `swap_e` (ex against ey there; both lines declared 52 m), the channel
    number is not the source folder, the channel comment does not start
    "phoenix: folder 7, tag E2" (ex) or carry "swap_e: the E2 input stored
    as ex", the contact readings are not the source input's pot_p and pot_n
    of empower_recmeta.json, the azimuth is not survey.yaml's 0 (ex) and 90
    (ey), or the dipole length not 52;
  - P3: the run comment does not carry
    `ingest.PHOENIX_SWAP_E_NOTE`, or its "dc rail" line does not give ex
    4.5 V and ey 0.9 V (0.9 x the replaced ranges of folders 7 and 0);
  - P4: without `swap_e`, J2's ex is not folder 0 with the e1 curve, ey
    folder 7 with e2, ex's rail 0.9 V and ey's 4.5 V, or any channel or
    run comment mentions swap_e; or `component_of(tag)` differs from
    `RENAME.get(tag, tag)` for any tag of the channel maps;
  - P5: G5 with `swap_e: true` and no dipole declared does not give ex
    E2's 85 m (dipole_85m) and ey E1's 100 m, or with `dipole_length_ex:
    60` and `dipole_length_ey: 40` declared ex 60 m and ey 40 m with the
    e2 and e1 curves;
  - P6: G5H, the bursts of G5 with `swap_e: true`, does not hold in every
    burst run ex equal to folder 7's burst (a walk of the sub-headers here
    with `struct`) and ey to folder 0's, ex's chain not the e2 curve and
    the same names as the continuous G5 archive's ex, the channel comments
    not naming folder 7 and E2 for ex, or a run comment without
    `PHOENIX_SWAP_E_NOTE`, or the dc rail line not ex 4.5 and ey 0.9;
  - P7: J2 with `swap_e: true` and `channels: [ex, hx, hy]` is ingested
    (it must be refused with "swap_e exchanges ex and ey").

P2's azimuth check could pass by accident if mt-io gave the E2 input 0 deg
of its own; the test reads mt-io's azimuth of folder 7's first file and
prints it (it must differ from 0 for the check to tell anything).

The mutations, each run on the checks it must fail: M1, the samples
exchanged but the stages, contact readings, folder and rail left with the
tags (upstream issue 414's form: `component_of` ignoring `swap_e` and the
run's ex and ey samples exchanged after the read), must fail P2; M2, the
declaration ignored (`component_of` ignoring `swap_e`), must fail P1; M3,
the rails keyed by the tags (`_phoenix_rails` called without `swapped_e`),
must fail P3; M4, the burst path's components taken by the tags, must
fail P6.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import mt_workbench.ingest as ingest  # noqa: E402
import mt_workbench.phoenix as phoenix  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SOURCES = {"J2": Path(r"D:\MT_DATA\MT_Kalkaroo_Workspace\raw_extracted\KD-J2"),
           "G5": Path(r"D:\MT_DATA\MT_Kalkaroo_Phoenix_TEST\G5")}
SENSORS = {"J2": Path(r"D:\MT_DATA\MT_Kalkaroo_Workspace\sensors"),
           "G5": Path(r"D:\MT_DATA\MT_Kalkaroo_Phoenix_TEST\sensors")}
SCRATCH = scratch_dir("ingest_swap_e_phoenix_unit")
DATA = SCRATCH / "data"
WORKSPACE = SCRATCH / "workspace"
SITE_FILES = ("empower_recmeta.json", "recmeta.json", "backend.log", "config.json")
# the input range each E folder's files are given during the ingests, in V (folder index to range)
RANGES = {7: 5.0, 0: 1.0}
FREQS = np.array([0.1, 1.0, 10.0, 100.0])
SWAPPED = {"ex": 7, "ey": 0, "hx": 3, "hy": 2}
PLAIN = {"ex": 0, "ey": 7, "hx": 3, "hy": 2}
TAG = {0: "E1", 7: "E2", 3: "H1", 2: "H2"}
J2_ENTRY = {"calibration_dir": str(SENSORS["J2"]), "dipole_length_ex": 52.0, "dipole_length_ey": 52.0,
            "coil_hx": "54042", "coil_hy": "54043"}


def make_cut(site: str, n150: int = 1, n24: int = 0) -> Path:
    """Copy the first files of each channel folder of a recording into scratch (the source is only read)."""
    src, dst = SOURCES[site], DATA / site
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in SITE_FILES:
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)
    for folder in sorted(p for p in src.iterdir() if p.is_dir() and p.name.isdigit()):
        (dst / folder.name).mkdir()
        for ext, count in ((".td_150", n150), (".td_24k", n24)):
            for f in sorted(folder.glob(f"*{ext}"), key=lambda p: int(p.stem.split("_")[3], 16))[:count]:
                shutil.copy2(f, dst / folder.name / f.name)
    return dst


def survey_for(sites: dict) -> Survey:
    """Return a scratch survey of the cuts."""
    config = {"name": "SWAP_E_PHOENIX", "instrument": "phoenix", "sample_rate": 150.0, "data_root": str(DATA),
              "workspace": str(WORKSPACE), "defaults": {"channels": ["ex", "ey", "hx", "hy"]}, "sites": sites}
    return Survey(config, SCRATCH)


def fake_range(kept):
    """Return an `input_range_v` that gives `RANGES` for the files of folders 7 and 0 and the file's own otherwise."""
    def input_range_v(path):
        folder = int(Path(path).parent.name)
        return RANGES[folder] if folder in RANGES else kept(path)
    return input_range_v


def run_ingest(survey: Survey, site: str) -> Path:
    """Ingest a site with the input ranges replaced (`fake_range`)."""
    kept = phoenix.input_range_v
    phoenix.input_range_v = fake_range(kept)
    try:
        return ingest_site(survey, site, overwrite=True)
    finally:
        phoenix.input_range_v = kept


def comment_text(value) -> str:
    """Return a comment's text, whether held as text, a dict or a Comment."""
    if isinstance(value, dict):
        return str(value.get("value") or "")
    return str(getattr(value, "value", value) or "")


def read_archive(path: Path, site: str) -> list[dict]:
    """Read every run of an archive back with mth5, as plain dicts."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    out = []
    try:
        station = m.get_station(site, survey=m.surveys_group.groups_list[0])
        for run_id in sorted(r for r in station.groups_list if r.startswith("sr")):
            group = station.get_run(run_id)
            run = {"id": run_id, "comment": str(group.metadata.comments.value or ""), "ch": {}}
            for comp in group.groups_list:
                ch = group.get_channel(comp)
                md = ch.metadata
                resp = ch.channel_response
                run["ch"][comp] = {
                    "data": np.asarray(ch.hdf5_dataset[()]),
                    "chain": [f.name for f in md.filters],
                    "response": resp.complex_response(FREQS) if resp.filters_list else None,
                    "number": int(md.channel_number),
                    "comment": comment_text(md.comments),
                    "azimuth": float(md.measurement_azimuth),
                    "dipole": float(getattr(md, "dipole_length", 0.0) or 0.0),
                    "contact": (float(md.contact_resistance.start), float(md.contact_resistance.end))
                    if md.type == "electric" else None,
                }
            out.append(run)
    finally:
        m.close_mth5()
    return out


def folder_samples(cut: Path, folder: int) -> np.ndarray:
    """Return a channel folder's `.td_150` samples read with numpy past the 128-byte header, files joined."""
    files = sorted((cut / str(folder)).glob("*.td_150"), key=lambda p: int(p.stem.split("_")[3], 16))
    return np.concatenate([np.fromfile(f, dtype="<f4", offset=128) for f in files])


def walk_bursts(path: Path) -> list[np.ndarray]:
    """Return a .td_24k file's whole bursts by walking its sub-headers with struct."""
    raw = path.read_bytes()
    out, offset = [], 128
    while offset + 32 <= len(raw):
        _stamp, n = struct.unpack_from("<II", raw, offset)
        if offset + 32 + 4 * n > len(raw):
            break
        out.append(np.frombuffer(raw, dtype="<f4", count=n, offset=offset + 32))
        offset += 32 + 4 * n
    return out


def contacts(cut: Path) -> dict:
    """Return each E input's (pot_p, pot_n) from the cut's empower_recmeta.json, by folder."""
    meta = json.loads((cut / "empower_recmeta.json").read_text(encoding="utf-8"))
    folder_of = {str(m["tag"]).upper(): int(m["idx"]) for m in meta["channel_map"]["mapping"]}
    return {folder_of[c["tag"].upper()]: (float(c["pot_p"]), float(c["pot_n"]))
            for c in meta["chconfig"]["chans"] if c["tag"].upper() in ("E1", "E2")}


def rail_line(comment: str) -> dict:
    """Return the run comment's "dc rail" values {channel: V}."""
    found = re.search(r"dc rail \(V, 90 % of the input range\): ([^;]+)", comment)
    if not found:
        return {}
    return {k: float(v) for k, v in re.findall(r"(\w+) ([0-9.eE+-]+)", found.group(1))}


def lowpass(receiver: str, tag: str) -> str:
    """Return the receiver curve stage name mt-io gives an input."""
    return f"mtu-8a_rmt05_{receiver}_{tag.lower()}_10000hz_lowpass"


def check_samples(cut: Path, runs: list[dict], source: dict, label: str) -> list[str]:
    """P1: every channel equals its source folder's samples."""
    bad = []
    if len(runs) != 1:
        return [f"{label}: {len(runs)} runs, 1 expected"]
    for comp, folder in source.items():
        got, want = runs[0]["ch"][comp]["data"], folder_samples(cut, folder)
        if got.shape != want.shape or not np.array_equal(got, want):
            bad.append(f"{label} {comp}: not folder {folder}'s samples")
    return bad


def check_inputs(cut: Path, runs: list[dict], source: dict, receiver: str, lengths: dict, label: str,
                 swap: bool) -> list[str]:
    """P2 and P4: each E channel carries its source input's curve, folder, comment and contact readings."""
    bad, pots = [], contacts(cut)
    run = runs[0]
    for comp in ("ex", "ey"):
        ch, folder = run["ch"][comp], source[comp]
        want = [f"dipole_{lengths[comp]:g}m", phoenix.MV_TO_V, lowpass(receiver, TAG[folder])]
        if ch["chain"] != want:
            bad.append(f"{label} {comp}: chain {ch['chain']}, want {want}")
        if ch["number"] != folder:
            bad.append(f"{label} {comp}: channel number {ch['number']}, want {folder}")
        if not ch["comment"].startswith(f"phoenix: folder {folder}, tag {TAG[folder]}"):
            bad.append(f"{label} {comp}: comment starts {ch['comment'][:40]!r}")
        if swap and f"swap_e: the {TAG[folder]} input stored as {comp}" not in ch["comment"]:
            bad.append(f"{label} {comp}: no swap_e piece in the channel comment")
        if not swap and "swap_e" in ch["comment"]:
            bad.append(f"{label} {comp}: swap_e in the comment of an unswapped site")
        if ch["contact"] != pots[folder]:
            bad.append(f"{label} {comp}: contact readings {ch['contact']}, want folder {folder}'s {pots[folder]}")
        if ch["dipole"] != lengths[comp]:
            bad.append(f"{label} {comp}: dipole_length {ch['dipole']}, want {lengths[comp]}")
        if ch["azimuth"] != {"ex": 0.0, "ey": 90.0}[comp]:
            bad.append(f"{label} {comp}: azimuth {ch['azimuth']}")
    for comp in ("hx", "hy"):
        want_curve = lowpass(receiver, TAG[source[comp]])
        if run["ch"][comp]["chain"][-1] != want_curve:
            bad.append(f"{label} {comp}: last stage {run['ch'][comp]['chain'][-1]}, want {want_curve}")
    return bad


def check_responses(swapped: list[dict], plain: list[dict]) -> list[str]:
    """P2: each E chain's response equals the same input's chain in the archive without swap_e."""
    bad = []
    for comp, other in (("ex", "ey"), ("ey", "ex")):
        got, want = swapped[0]["ch"][comp]["response"], plain[0]["ch"][other]["response"]
        rel = float(np.max(np.abs(got - want) / np.abs(want)))
        if rel > 1e-12:
            bad.append(f"J2 swap {comp}: response differs from the plain {other} by {rel:.3e} relative")
    return bad


def check_run(runs: list[dict], swap: bool, label: str) -> list[str]:
    """P3 and P4: the run comment's note and rail line."""
    bad = []
    for run in runs:
        has = ingest.PHOENIX_SWAP_E_NOTE in run["comment"]
        if has != swap:
            bad.append(f"{label} {run['id']}: PHOENIX_SWAP_E_NOTE {'missing' if swap else 'present'}")
        if not swap and "swap_e" in run["comment"]:
            bad.append(f"{label} {run['id']}: swap_e in the run comment")
        rails = rail_line(run["comment"])
        want = {"ex": 4.5, "ey": 0.9} if swap else {"ex": 0.9, "ey": 4.5}
        got = {c: rails.get(c) for c in want}
        if any(got[c] is None or abs(got[c] - want[c]) > 1e-9 for c in want):
            bad.append(f"{label} {run['id']}: dc rail {got}, want {want}")
    return bad


def p1(j2: Path) -> list[str]:
    runs = read_archive(run_ingest(survey_for({"J2": {**J2_ENTRY, "swap_e": True}}), "J2"), "J2")
    return check_samples(j2, runs, SWAPPED, "J2 swap")


def p2(j2: Path) -> list[str]:
    swapped = read_archive(run_ingest(survey_for({"J2": {**J2_ENTRY, "swap_e": True}}), "J2"), "J2")
    plain = read_archive(run_ingest(survey_for({"J2": dict(J2_ENTRY)}), "J2"), "J2")
    return (check_inputs(j2, swapped, SWAPPED, "10135", {"ex": 52.0, "ey": 52.0}, "J2 swap", True)
            + check_responses(swapped, plain))


def p3(_j2: Path) -> list[str]:
    runs = read_archive(run_ingest(survey_for({"J2": {**J2_ENTRY, "swap_e": True}}), "J2"), "J2")
    return check_run(runs, True, "J2 swap")


def p4(j2: Path) -> list[str]:
    runs = read_archive(run_ingest(survey_for({"J2": dict(J2_ENTRY)}), "J2"), "J2")
    bad = (check_samples(j2, runs, PLAIN, "J2 plain")
           + check_inputs(j2, runs, PLAIN, "10135", {"ex": 52.0, "ey": 52.0}, "J2 plain", False)
           + check_run(runs, False, "J2 plain"))
    for tag in ("e1", "e2", "h1", "h2", "h3", "h4", "h5", "h6"):
        if phoenix.component_of(tag) != phoenix.RENAME.get(tag, tag):
            bad.append(f"component_of({tag!r}) = {phoenix.component_of(tag)!r}, RENAME gives "
                       f"{phoenix.RENAME.get(tag, tag)!r}")
    return bad


def p5(g5: Path) -> list[str]:
    base = {"calibration_dir": str(SENSORS["G5"]), "swap_e": True}
    bad = []
    for entry, lengths in ((base, {"ex": 85.0, "ey": 100.0}),
                           ({**base, "dipole_length_ex": 60.0, "dipole_length_ey": 40.0}, {"ex": 60.0, "ey": 40.0})):
        runs = read_archive(run_ingest(survey_for({"G5": entry}), "G5"), "G5")
        bad += check_samples(g5, runs, SWAPPED, f"G5 swap {lengths}")
        bad += check_inputs(g5, runs, SWAPPED, "10133", lengths, f"G5 swap {lengths}", True)
    return bad


def p6(g5: Path) -> list[str]:
    sites = {"G5": {"calibration_dir": str(SENSORS["G5"]), "swap_e": True},
             "G5H": {"bursts_of": "G5", "sample_rate": 24000}}
    survey = survey_for(sites)
    continuous = read_archive(run_ingest(survey, "G5"), "G5")
    runs = read_archive(run_ingest(survey, "G5H"), "G5H")
    files = {f: next((g5 / str(f)).glob("*.td_24k")) for f in (0, 7)}
    walks = {f: walk_bursts(p) for f, p in files.items()}
    bad = [] if len(runs) == len(walks[7]) else [f"G5H: {len(runs)} runs, the walk gives {len(walks[7])} bursts"]
    for k, run in enumerate(runs[:len(walks[7])]):
        for comp, folder in (("ex", 7), ("ey", 0)):
            ch = run["ch"][comp]
            if not np.array_equal(ch["data"], walks[folder][k]):
                bad.append(f"G5H {run['id']} {comp}: not folder {folder}'s burst {k}")
            if ch["chain"] != continuous[0]["ch"][comp]["chain"] or ch["chain"][-1] != lowpass("10133", TAG[folder]):
                bad.append(f"G5H {run['id']} {comp}: chain {ch['chain']}")
            if not ch["comment"].startswith(f"phoenix: folder {folder}, tag {TAG[folder]}"):
                bad.append(f"G5H {run['id']} {comp}: comment starts {ch['comment'][:40]!r}")
    bad += check_run(runs, True, "G5H")
    return bad[:12]


def p7(_j2: Path) -> list[str]:
    survey = survey_for({"J2": {**J2_ENTRY, "swap_e": True, "channels": ["ex", "hx", "hy"]}})
    try:
        run_ingest(survey, "J2")
    except ValueError as exc:
        return [] if "swap_e exchanges ex and ey" in str(exc) else [f"J2 without ey: refused with {exc}"]
    return ["J2 swap_e without ey was ingested"]


def mutated(changes: list[tuple], check, *args) -> list[str]:
    """Run a check with module attributes replaced, and return what it reports."""
    kept = [(target, name, getattr(target, name)) for target, name, _value in changes]
    for target, name, value in changes:
        setattr(target, name, value)
    try:
        return check(*args)
    finally:
        for target, name, value in kept:
            setattr(target, name, value)


def by_tags(tag, swap_e=False):
    """`component_of` ignoring `swap_e`: every input under its tag's name."""
    return phoenix.RENAME.get(tag, tag)


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    j2, g5 = make_cut("J2"), make_cut("G5", n150=1, n24=1)
    from mt_io.phoenix.read import open_phoenix
    reader = open_phoenix(next((j2 / "7").glob("*.td_150")))
    try:
        mtio_azimuth = float(reader.channel_metadata.measurement_azimuth)
    finally:
        reader.close()
    print(f"  mt-io's own azimuth of J2 folder 7 (E2): {mtio_azimuth:g} deg (P2's ex azimuth check needs it "
          f"not 0)")
    failures, trips = [], []
    for name, check, cut in (("P1", p1, j2), ("P2", p2, j2), ("P3", p3, j2), ("P4", p4, j2), ("P5", p5, g5),
                             ("P6", p6, g5), ("P7", p7, j2)):
        bad = check(cut)
        failures += bad
        print(f"  {name}: {'ok' if not bad else bad}")

    kept_read = phoenix.read_continuous

    def samples_only(rec, plan, site, calibration_dir=None):
        run, pieces, correction = kept_read(rec, plan, site, calibration_dir)
        if getattr(site, "swap_e", False):
            ex, ey = run.dataset["ex"].data, run.dataset["ey"].data
            run.dataset["ex"].data, run.dataset["ey"].data = ey, ex
        return run, pieces, correction

    kept_rails = ingest._phoenix_rails
    for label, changes, check, cut in (
            ("M1 (samples exchanged, stages left with the tags: the upstream-414 form) on P2",
             [(phoenix, "component_of", by_tags), (phoenix, "read_continuous", samples_only)], p2, j2),
            ("M2 (swap_e ignored) on P1", [(phoenix, "component_of", by_tags)], p1, j2),
            ("M3 (rails keyed by the tags) on P3",
             [(ingest, "_phoenix_rails", lambda rec, files, swapped=False, swapped_e=False:
               kept_rails(rec, files, swapped))], p3, j2),
            ("M4 (burst components by the tags) on P6", [(phoenix, "component_of", by_tags)], p6, g5)):
        trip = mutated(changes, check, cut)
        trips.append((label, trip))
        for line in trip:
            print(f"    {line}")
        print(f"  {label}: {'FAILED as it must' if trip else 'PASSED: the check cannot fail'} "
              f"({len(trip)} failure(s){': ' + trip[0][:150] if trip else ''})")
    dead = [label for label, trip in trips if not trip]
    if failures or dead or mtio_azimuth == 0.0:
        print("\nFAIL  ingest_swap_e_phoenix_unit")
        for line in failures + [f"mutation did not trip: {d}" for d in dead]:
            print(f"  {line}")
        raise SystemExit(1)
    shutil.rmtree(DATA)
    print("\nPASS  ingest_swap_e_phoenix_unit")


if __name__ == "__main__":
    main()
