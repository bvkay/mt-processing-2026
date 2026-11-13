# -*- coding: utf-8 -*-
"""
Unit test for the provenance a `swap_h` exchange keeps (mt_workbench.ingest)

Two synthetic MTU-5A sites are written with the writers of
tests/mtu5a_unit.py (a `.TS4` of three 1 s records at 150 Hz and its
`.TBL`), each table carrying three distinct coil serials under HXSN, HYSN
and HZSN and the channel numbers of mtu5a_unit (hx 3, hy 5, hz 4). They are
sites of one scratch survey (instrument mtu5a, 150 Hz): SWP declared
`swap_h: true`, PLN with no key. Both are ingested with `ingest_site`, and
the archives are read back with mth5, never through the code under test,
and compared with the counts and table values written here. The swap_h
site is ingested once more into a second scratch workspace with the old
`_swap_h` (kept here unchanged as `_swap_h_old`: the filter chain alone
moved, the comment replaced, the sensor attrs left with the channel
names) monkeypatched in, and the same checks are run on it.

Usage:
    python tests/ingest_swap_h_provenance_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - P1: the swap_h site's archived hx does not carry sensor.id = the
    table's HYSN, or its comment does not hold "channel 5 (CHHY)" and
    "coil <HYSN> (HYSN)" and, after them, a "swap_h:" piece naming "the hy
    input";
  - P2: its hy does not carry the HXSN twin: sensor.id = HXSN, "channel 3
    (CHHX)", "coil <HXSN> (HXSN)" and then a "swap_h:" piece naming "the
    hx input";
  - P3: its hz does not carry its own HZSN, "channel 4 (CHHZ)" and no
    "swap_h:" piece;
  - P4: its hx is not the hy input's written counts sample for sample with
    the hy input's filter chain (the PLN archive's hy chain), its hy not
    the hx input's with the hx input's chain, or hx and hy do not keep
    their own channel numbers (3, 5) and azimuths (0, 90);
  - P5: the PLN site's hx, hy and hz do not carry their own HXSN, HYSN and
    HZSN, their own "channel N (CHHx)" and coil pieces, no "swap_h:"
    piece, and their own inputs' counts;
  - P6: the swap_h site's run comment does not record "swap_h: hx and hy
    exchanged";
  - the mutation (the old `_swap_h`) passes P1 or P2: then the provenance
    checks cannot fail and the test is void, reported as such, not PASS.

The MTU-5A kind writes one magnetic chain per recording (HNOM, HATT,
HGN and the converter, from the table), so hx's and hy's chains are equal
by name and gain and P4's chain clause cannot tell them apart here; the
chain's move is tested where the inputs' chains differ, in
tests/ingest_swap_h_unit.py (LEMI-423, each input's own coefficient).
"""

from __future__ import annotations

import shutil
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from loguru import logger  # noqa: E402

import mt_workbench.ingest as ingest  # noqa: E402
from mt_workbench.ingest import ingest_site  # noqa: E402
from mt_workbench.mtu5a import COIL_KEYS  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mtu5a_unit import ORDER, START, record_counts, write_tbl, write_ts4  # noqa: E402

SCRATCH = scratch_dir("ingest_swap_h_provenance_unit")
SERIAL = 4573
STEM = "4573C07A"
RUN = "sr150_0001"
SECONDS = [0, 1, 2]
# three distinct coil serials, none equal to mtu5a_unit's TABLE defaults
COILS = {"HXSN": "BMT53817", "HYSN": "BMT53813", "HZSN": "BMT53901"}
CHANNEL_KEY = {"hx": "CHHX", "hy": "CHHY", "hz": "CHHZ"}
AZIMUTH = {"hx": 0.0, "hy": 90.0}
RUN_NOTE = "swap_h: hx and hy exchanged"


def _swap_h_old(run, site) -> str | None:
    """The earlier `_swap_h` of ingest.py, unchanged: the mutation."""
    if not site.swap_h:
        return None
    if not all(comp in run.dataset for comp in ("hx", "hy")):
        raise ValueError(f"{site.name}: swap_h exchanges hx and hy, and the run holds "
                         f"{list(run.dataset.data_vars)}")
    # run.<comp> accessors return copies, so run.dataset is modified directly
    hx, hy = run.dataset["hx"].data, run.dataset["hy"].data
    run.dataset["hx"].data, run.dataset["hy"].data = hy, hx
    for key in ("filters",):  # the old module's _INPUT_ATTRS
        hx_attr, hy_attr = run.dataset["hx"].attrs.get(key), run.dataset["hy"].attrs.get(key)
        run.dataset["hx"].attrs[key], run.dataset["hy"].attrs[key] = hy_attr, hx_attr
    for comp, source in (("hx", "hy"), ("hy", "hx")):
        run.dataset[comp].attrs["comments"] = f"swap_h: the samples and filter chain of the {source} input"
    logger.info(f"{site.name}: swap_h -> hx and hy exchanged (hx holds the hy input, hy the hx input)")
    return "swap_h: hx and hy exchanged, each with the filter chain of the input it was recorded on"


def write_site(data: Path, name: str) -> dict:
    """Write one site folder (one recording, three records); return the written counts by table column."""
    folder = data / name
    folder.mkdir(parents=True)
    counts = write_ts4(folder / f"{STEM}.TS4", SECONDS, SERIAL)
    write_tbl(folder / f"{STEM}.TBL", START, START + timedelta(seconds=SECONDS[-1]), SNUM=SERIAL, **COILS)
    joined = np.concatenate([counts[k] for k in range(len(SECONDS))], axis=0)
    assert np.array_equal(joined[:150], record_counts(0))
    # the input of each channel name: its table column's counts
    return {comp: joined[:, ORDER[comp] - 1].astype(np.int32) for comp in ("hx", "hy", "hz")}


def survey_for(root: Path) -> Survey:
    """Return the scratch survey of the two sites under `root`."""
    config = {"name": "MTU5A_TEST", "instrument": "mtu5a", "sample_rate": 150.0, "data_root": str(root / "data"),
              "workspace": str(root / "workspace"),
              "sites": {"SWP": {"dipole_length_ex": 100.0, "swap_h": True}, "PLN": {"dipole_length_ex": 100.0}}}
    return Survey(config, root)


def read_back(path: Path, site: str) -> dict:
    """Read the run's comment and, per coil channel, samples, sensor id, comment, number, azimuth and chain."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    out = {}
    try:
        station = m.get_station(site, survey=m.surveys_group.groups_list[0])
        group = station.get_run(RUN)
        out["comment"] = str(group.metadata.comments.value or "")
        for comp in ("hx", "hy", "hz"):
            ch = group.get_channel(comp)
            md = ch.metadata
            comment = getattr(md.comments, "value", md.comments)
            out[comp] = dict(samples=np.asarray(ch.hdf5_dataset[()]), sensor=str(md.sensor.id or ""),
                             comment=str(comment or ""), number=int(md.channel_number),
                             azimuth=float(md.measurement_azimuth),
                             chain=[(f.name, float(getattr(f, "gain", 1.0) or 1.0))
                                    for f in ch.channel_response.filters_list])
    finally:
        m.close_mth5()
    return out


def provenance(row: dict, source: str, swapped_from: str | None) -> list[str]:
    """Return what is wrong with a channel's sensor id and comment for the input `source`; empty when right.

    `swapped_from` names the input the "swap_h:" piece must name (after the
    channel and coil pieces), or None when there must be no such piece.
    """
    serial_key = COIL_KEYS[source]
    serial, number, column = COILS[serial_key], ORDER[source], CHANNEL_KEY[source]
    bad = []
    if row["sensor"] != serial:
        bad.append(f"sensor.id {row['sensor']!r}, expected {serial} ({serial_key})")
    comment = row["comment"]
    channel_piece, coil_piece = f"channel {number} ({column})", f"coil {serial} ({serial_key})"
    at = [comment.find(channel_piece), comment.find(coil_piece)]
    if at[0] < 0:
        bad.append(f"comment lacks {channel_piece!r}")
    if at[1] < 0:
        bad.append(f"comment lacks {coil_piece!r}")
    swap_at = comment.find("swap_h:")
    if swapped_from is None:
        if swap_at >= 0:
            bad.append(f"comment holds a swap_h piece: {comment[swap_at:]!r}")
    elif swap_at < 0:
        bad.append("comment lacks a swap_h piece")
    else:
        if f"the {swapped_from} input" not in comment[swap_at:]:
            bad.append(f"swap_h piece does not name the {swapped_from} input: {comment[swap_at:]!r}")
        if any(k >= 0 and k > swap_at for k in at):
            bad.append("swap_h piece is not after the channel and coil pieces")
    return bad


def check_swapped(got: dict, inputs: dict, plain: dict) -> dict:
    """Return P1-P4 and P6's problems for a swap_h archive, by group."""
    groups = {
        "P1 swap_h hx provenance (HYSN, CHHY, then the swap_h piece naming the hy input)":
            provenance(got["hx"], "hy", "hy"),
        "P2 swap_h hy provenance (HXSN, CHHX, then the swap_h piece naming the hx input)":
            provenance(got["hy"], "hx", "hx"),
        "P3 swap_h hz provenance (own HZSN, CHHZ, no swap_h piece)": provenance(got["hz"], "hz", None),
    }
    bad = []
    for comp, source in (("hx", "hy"), ("hy", "hx")):
        if not np.array_equal(got[comp]["samples"], inputs[source]):
            bad.append(f"{comp} samples are not the {source} input's written counts")
        if got[comp]["chain"] != plain[source]["chain"]:
            bad.append(f"{comp} chain {got[comp]['chain']} is not the {source} input's {plain[source]['chain']}")
        if got[comp]["number"] != ORDER[comp]:
            bad.append(f"{comp} channel_number {got[comp]['number']}, expected its own {ORDER[comp]}")
        if got[comp]["azimuth"] != AZIMUTH[comp]:
            bad.append(f"{comp} azimuth {got[comp]['azimuth']}, expected its own {AZIMUTH[comp]}")
    if not np.array_equal(got["hz"]["samples"], inputs["hz"]):
        bad.append("hz samples are not the hz input's")
    groups["P4 swap_h samples, chains (move) and channel numbers, azimuths (stay)"] = bad
    groups["P6 swap_h run comment"] = [] if RUN_NOTE in got["comment"] else [f"run comment {got['comment']!r}"]
    return groups


def check_plain(got: dict, inputs: dict) -> list[str]:
    """Return P5's problems for the unswapped archive."""
    bad = []
    for comp in ("hx", "hy", "hz"):
        bad += [f"{comp}: {p}" for p in provenance(got[comp], comp, None)]
        if not np.array_equal(got[comp]["samples"], inputs[comp]):
            bad.append(f"{comp} samples are not its own input's")
    if "swap_h" in got["comment"]:
        bad.append(f"run comment records a swap: {got['comment']!r}")
    return bad


def main() -> int:
    """Run the current code's checks and the mutation's; print one line per group; return the exit status."""
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nThe MTU-5A kind")[0])
    print()
    assert len(set(COILS.values())) == 3, COILS
    assert ingest._swap_h is not _swap_h_old
    root = SCRATCH / "fixed"
    shutil.rmtree(root, ignore_errors=True)
    inputs = {name: write_site(root / "data", name) for name in ("SWP", "PLN")}
    survey = survey_for(root)
    paths = {name: ingest_site(survey, name, overwrite=True) for name in ("SWP", "PLN")}
    got = {name: read_back(path, name) for name, path in paths.items()}

    failed = []
    groups = check_swapped(got["SWP"], inputs["SWP"], got["PLN"])
    groups["P5 unswapped site: own HXSN HYSN HZSN, own inputs, no swap_h piece"] = check_plain(got["PLN"],
                                                                                              inputs["PLN"])
    for label, bad in groups.items():
        print(f"  {'ok  ' if not bad else 'FAIL'}  {label}" + ("" if not bad else f": {bad}"))
        if bad:
            failed.append(label)
    print(f"        archived hx comment: {got['SWP']['hx']['comment']!r}")
    print(f"        archived hy comment: {got['SWP']['hy']['comment']!r}")

    # the mutation: the old _swap_h, into a second scratch workspace
    mroot = SCRATCH / "mutant"
    shutil.rmtree(mroot, ignore_errors=True)
    minputs = {"SWP": write_site(mroot / "data", "SWP")}
    real = ingest._swap_h
    ingest._swap_h = _swap_h_old
    try:
        mpath = ingest_site(survey_for(mroot), "SWP", overwrite=True)
    finally:
        ingest._swap_h = real
    mgroups = check_swapped(read_back(mpath, "SWP"), minputs["SWP"], got["PLN"])
    for label, bad in mgroups.items():
        print(f"  mutation {'tripped' if bad else 'passed '}  {label}" + ("" if not bad else f": {bad}"))
    tripped = all(mgroups[k] for k in mgroups if k.startswith(("P1", "P2")))
    if not tripped:
        print("\nVOID  ingest_swap_h_provenance_unit: the old _swap_h passed P1 or P2, so they cannot fail")
        return 1
    if failed:
        print(f"\nFAIL  ingest_swap_h_provenance_unit: {failed}")
        return 1
    print(f"\nPASS  ingest_swap_h_provenance_unit ({len(groups)} groups; the mutation (old _swap_h) failed P1 and "
          f"P2, as it must)")
    return 0


if __name__ == "__main__":
    logger.remove()  # the readers' INFO lines would bury the test's own
    logger.add(sys.stderr, level="ERROR")
    sys.exit(main())
