# -*- coding: utf-8 -*-
"""
Unit test for the Phoenix entries of mt_workbench.instruments

A scratch data root holds four synthetic Phoenix recordings and three
folders of other recorders. Each Phoenix file is a 128-byte header written
here with `struct` at the offsets of Phoenix's file format (the layout
mt-io's `Header` reads), followed by float32 samples, in the folder layout
of a receiver: a recording folder with empower_recmeta.json beside
numbered channel folders. MTU8 is an MTU-8A (receiver 10133, folders 0 2 3
7), MTU5 an MTU-5C (receiver 10240, folders 0 1 2 4), and each channel
folder holds three `.td_150` files (sequence 1 of 359 s, then 360 s each)
and one `.td_24k` file of two bursts. Beside them: an AppleDouble twin
(``._<name>.td_150``), a `.td_2400` file and a `.td_150` whose name is not a
Phoenix name. The other folders hold a B423 file, a LEMI-424 day file and
an EDL channel file.

Usage:
    python tests/phoenix_files_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - `is_record` accepts the AppleDouble twin, the `.td_2400` file or the
    badly named `.td_150`, or refuses a `.td_150`, `.td_30` or `.td_24k`
    with a Phoenix name of either receiver;
  - `Survey.site_dirs()` does not list exactly the seven data folders, or
    `instrument_of` does not give phoenix for both Phoenix folders and
    lemi423, lemi424 and edl for the others (in a lemi423 and in a phoenix
    survey);
  - `file_start` of a continuous file is not the recording id in the name
    less 18 leap seconds, plus 1 s for sequence 1 and plus 360 s x
    (sequence - 1) for the others, or that of a burst file is not its first
    sub-header's stamp less 18 s;
  - `record_files` does not list 4 x 4 files of each recording, sorted by
    type, then channel folder, then sequence, with the twin, the
    `.td_2400` and the bad name left out;
  - `span` is not the first file's start to the last file's end (sequence
    3's start plus its 54000 samples at 150 Hz), with three files counted;
  - `header_facts` does not read the receiver id, the model (MTU-8A from
    RMT05, MTU-5C from RMT03-D), the position and the channels switched
    on (renamed ex ey hx hy) from empower_recmeta.json rather than the
    recmeta.json beside it, or the rate from the header;
  - scripts/new_survey.py on the Phoenix folders does not write a survey
    whose `Survey.site` gives each site its receiver as `serial`, dipole
    lengths 0.0 (the receiver metadata's at ingest), `calibration_dir:
    sensors` and the aligned min_period 4**(22/6)/6000;
  - the run plan (`mt_workbench.phoenix.plan_runs` of `recording_files`)
    of a synthetic MTU-8A recording of four `.td_150` files per folder
    (sequence 1 of 359 s, then 360 s each) is not: one run of sequences
    1-4 with no gap note when the folders agree, and when a 0-byte
    sequence 5 trails in every folder (each of the four empty files named
    in a warning); two runs, 1 and 3-4, the same sequences in every
    folder, with a "phoenix_gap" note on the second naming sequence 2,
    the folder and 360 s, when sequence 2 is missing from folder 3, is
    0 bytes there (named in a warning), or is 60 s shorter there than in
    the other folders;
  - the calibration-date rule (`phoenix.calibration_for` through
    `_coil_stage` and `_rxcal`, on synthetic ``<serial>_<epoch
    hex>.scal.json`` and ``.rxcal.json`` files of three dates) does not
    take: the earliest file for a recording before the first date, the
    latest at or before the start between two dates, the file of the day
    for a start on its epoch and hours after it, the last after the last
    date, the one file of a coil with one file before and after its date,
    of a receiver's two files ten minutes apart on one day the earlier for
    a start between them and the later after both, nothing for a coil
    with no file (FileNotFoundError for a receiver), or a refusal for
    several files and no start; or `calibration_date` does not give the
    file's UTC date;
  - a calibration file dated after the recording's start is taken without
    one warning line naming the unit, the file and the days (the earliest
    of three coil files for a start 3 days before the first, 3.0 days; the
    one file of a coil for a start 30 days before it), the choice changes
    with the warning, or a warning is logged when a file at or before the
    start exists;
  - `_rxcal_dates`, the date part of the channel comment's rxcal piece,
    does not give "calibrated <date>" for an EMpower rxcal file and
    "records calibrated <date>; curve below 1024 Hz from <file>" for low
    pass 10000 of a converted one (`curve_below_records_from` in it), or
    "curve below the records from <file>" for a low pass of no known band.

The mutations: with the leap seconds left out of `gps_to_utc_seconds`,
the `file_start` check must fail by 18 s; with new_survey.py's Phoenix
defaults left out, the survey check must fail (dipoles 50 m); with
`phoenix._aligned_files` keeping each folder's own files (mt-io's
`read_sequence` joins a folder's files the same way), the missing-sequence
case must fail (folder 3's run files off by one sequence); with the date
rule reversed (the earliest at or after the start, else the latest
before), the between-two and same-day receiver cases must fail (before
the first and after the last its fallback gives the same file); with the
warning left out (`_warn_after_start` a no-op), the after-start cases
must fail; with `_rxcal_dates` giving the date alone (the comment of the
first calibrations diff), the converted rxcal case must fail.
"""

from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

import mt_workbench.instruments as instruments  # noqa: E402
from mt_workbench.instruments import file_start, header_facts, is_record, record_files, span  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRATCH = scratch_dir("phoenix_files_unit")
REC_ID = 0x5FA4809A  # GPS seconds, 2020-11-05 22:45:46 GPS = 22:45:28 UTC
LEAP = 18
RECEIVERS = {"MTU8": ("10133", "RMT05", {0: "E1", 2: "H2", 3: "H1", 7: "E2"}),
             "MTU5": ("10240", "RMT03-D", {0: "H2", 1: "E1", 2: "H1", 4: "E2"})}
LEMI424_LINE = ("2024 10 25 00 00 00 27150.959 -74.552 -50540.593 27.73 36.16 -154.411 -297.117 "
                "94.135 -767.370 12.00  512.8 2800.28816 S 12054.72277 E 12 2 0\n")


def phoenix_head(receiver: str, channel: int, seq: int, rate_base: int, rate_exp: int = 0,
                 frag: int = 360, version: int = 2) -> bytes:
    """Return a 128-byte Phoenix header with the fields ingest reads at their byte offsets."""
    head = bytearray(128)
    head[0], head[1] = 1, version
    struct.pack_into("<H", head, 2, 128)
    head[4:12] = b"MTU-5C\x00\x00"
    head[12:20] = receiver.encode().ljust(8, b"\x00")
    struct.pack_into("<I", head, 20, REC_ID)
    head[24] = channel
    struct.pack_into("<I", head, 25, seq)
    struct.pack_into("<H", head, 29, frag)
    struct.pack_into("<Hb", head, 59, rate_base, rate_exp)
    return bytes(head)


def write_recording(folder: Path, receiver: str, model: str, mapping: dict) -> list[Path]:
    """Write one synthetic recording: metadata files and four files per channel folder."""
    folder.mkdir(parents=True)
    chans = [{"tag": tag, "on": 1, "length1": 50, "length2": 50} for tag in mapping.values()]
    meta = {"instid": receiver, "sw_version": "v1.54.2", "receiver_model": model,
            "channel_map": {"mapping": [{"idx": i, "tag": t} for i, t in mapping.items()], "receiver_model": model},
            "chconfig": {"chans": chans},
            "timing": {"gps_lat": -31.738548, "gps_lon": 140.527259, "gps_alt": 123.4}}
    (folder / "empower_recmeta.json").write_text(json.dumps(meta))
    (folder / "recmeta.json").write_text(json.dumps({**meta, "instid": "99999"}))
    written = []
    for idx in mapping:
        ch = folder / str(idx)
        ch.mkdir()
        for seq in (1, 2, 3):
            n = 150 * (359 if seq == 1 else 360)
            path = ch / f"{receiver}_{REC_ID:08X}_{idx}_{seq:08X}.td_150"
            path.write_bytes(phoenix_head(receiver, idx, seq, 150) + np.zeros(n, "<f4").tobytes())
            written.append(path)
        bursts = b"".join(struct.pack("<II", REC_ID + 14 + 30 * k, 480) + bytes(24) + np.zeros(480, "<f4").tobytes()
                          for k in range(2))
        path = ch / f"{receiver}_{REC_ID:08X}_{idx}_{1:08X}.td_24k"
        path.write_bytes(phoenix_head(receiver, idx, 1, 24, 3) + bursts)
        written.append(path)
    return written


def build_root() -> Path:
    root = SCRATCH / "root"
    if root.exists():
        shutil.rmtree(root)
    for site, (receiver, model, mapping) in RECEIVERS.items():
        write_recording(root / site, receiver, model, mapping)
    extra = root / "MTU8" / "0"
    first = next(extra.glob("*_00000001.td_150"))
    (extra / f"._{first.name}").write_bytes(bytes(4096))
    (extra / f"10133_{REC_ID:08X}_0_00000001.td_2400").write_bytes(phoenix_head("10133", 0, 1, 24, 2))
    (extra / "notes_copy.td_150").write_bytes(first.read_bytes())
    others = {"S01/1624949744.B423": b"", "MBJ21/202410250000.txt": LEMI424_LINE.encode(),
              "EGF01/001/EGF01_190110000000.EX": b"1\n2\n"}
    for name, data in others.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root


def check_names(root: Path) -> None:
    folder = root / "MTU8" / "0"
    good = [p for p in folder.iterdir() if p.suffix in (".td_150", ".td_24k") and not p.name.startswith(("._", "notes"))]
    assert len(good) == 4 and all(is_record(p, "phoenix") for p in good), [p.name for p in good]
    td30 = folder / f"10133_{REC_ID:08X}_0_00000004.td_30"
    assert is_record(td30, "phoenix") and is_record(root / "MTU5" / "1" / f"10240_{REC_ID:08X}_1_00000001.td_150", "phoenix")
    for bad in (f"._10133_{REC_ID:08X}_0_00000001.td_150", f"10133_{REC_ID:08X}_0_00000001.td_2400", "notes_copy.td_150"):
        assert not is_record(folder / bad, "phoenix"), bad
    print("  names: td_150, td_30, td_24k of both receivers accepted; the ._ twin, td_2400 and a bad name refused")


def check_detection(root: Path) -> None:
    expected = {"EGF01": "edl", "MBJ21": "lemi424", "MTU5": "phoenix", "MTU8": "phoenix", "S01": "lemi423"}
    for prefer in ("lemi423", "phoenix"):
        survey = Survey({"name": "t", "instrument": prefer, "data_root": str(root)}, root)
        assert list(survey.site_dirs()) == sorted(expected), list(survey.site_dirs())
        got = {s: survey.instrument_of(s) for s in expected}
        assert got == expected, (prefer, got)
    print(f"  detection in a lemi423 and a phoenix survey: {expected}")


def expected_start(seq: int) -> int:
    utc = REC_ID - LEAP
    return utc + 1 if seq == 1 else utc + 360 * (seq - 1)


def check_starts(root: Path) -> list[str]:
    bad = []
    for path in sorted((root / "MTU5" / "4").iterdir()):
        seq = int(path.stem.split("_")[3], 16)
        want = REC_ID + 14 - LEAP if path.suffix == ".td_24k" else expected_start(seq)
        got = file_start(path, "phoenix")
        if got != want:
            bad.append(f"{path.name}: {got} != {want} ({got - want:+d} s)")
    return bad


def check_listing(root: Path) -> None:
    for site, (receiver, model, mapping) in RECEIVERS.items():
        files = record_files(root / site, "phoenix")
        assert len(files) == 4 * len(mapping), (site, len(files))
        want = [(".td_150", idx, seq) for idx in sorted(mapping) for seq in (1, 2, 3)] + \
               [(".td_24k", idx, 1) for idx in sorted(mapping)]
        got = [(p.suffix, int(p.stem.split("_")[2]), int(p.stem.split("_")[3], 16)) for p in files]
        assert got == want, (site, got[:6])
        start, end, n = span(root / site, "phoenix", files)
        assert (int(start.timestamp()), int(end.timestamp()), n) == (expected_start(1), expected_start(3) + 360, 3), \
            (site, start, end, n)
        facts = header_facts(root / site, "phoenix", files)
        want_model = "MTU-8A" if model == "RMT05" else "MTU-5C"
        assert (facts["serial"], facts["model"], facts["sample_rate"]) == (receiver, want_model, 150.0), facts
        assert facts["columns"] == ["ex", "ey", "hx", "hy"] and facts["latitude"] == -31.738548, facts
    print(f"  record_files: 16 files per recording in type, folder, sequence order; span {start} to {end}, "
          f"3 files; header_facts {facts['serial']} {facts['model']} from empower_recmeta.json")


GAP_FOLDER = 3  # MTU8's H1 (hx), the folder E10 of S1 lacks a sequence in


def write_gap_recording(folder: Path, edit: str) -> None:
    """Write MTU8's recording with four `.td_150` files per folder and one edit.

    Args:
        folder (Path): The recording folder, made here.
        edit (str): "none"; "trailing_empty" (a 0-byte sequence 5 in every
            folder); "missing" (sequence 2 deleted from `GAP_FOLDER`);
            "empty" (sequence 2 of `GAP_FOLDER` cut to 0 bytes); "short"
            (sequence 2 of `GAP_FOLDER` 60 s shorter).
    """
    receiver, model, mapping = RECEIVERS["MTU8"]
    folder.mkdir(parents=True)
    meta = {"instid": receiver, "receiver_model": model,
            "channel_map": {"mapping": [{"idx": i, "tag": t} for i, t in mapping.items()], "receiver_model": model}}
    (folder / "empower_recmeta.json").write_text(json.dumps(meta))
    for idx in mapping:
        ch = folder / str(idx)
        ch.mkdir()
        for seq in (1, 2, 3, 4):
            n = 150 * (359 if seq == 1 else 360)
            if idx == GAP_FOLDER and seq == 2 and edit == "short":
                n -= 150 * 60
            data = phoenix_head(receiver, idx, seq, 150) + (np.full(n, idx * 10 + seq, "<f4")).tobytes()
            if idx == GAP_FOLDER and seq == 2 and edit == "empty":
                data = b""
            if not (idx == GAP_FOLDER and seq == 2 and edit == "missing"):
                (ch / f"{receiver}_{REC_ID:08X}_{idx}_{seq:08X}.td_150").write_bytes(data)
        if edit == "trailing_empty":
            (ch / f"{receiver}_{REC_ID:08X}_{idx}_{5:08X}.td_150").write_bytes(b"")


def check_gaps() -> list[str]:
    """Plan the runs of each gap case. Returns the failures."""
    from loguru import logger

    from mt_workbench.phoenix import open_recording, plan_runs, recording_files

    want = {"none": [[1, 2, 3, 4]], "trailing_empty": [[1, 2, 3, 4]], "missing": [[1], [3, 4]],
            "empty": [[1], [3, 4]], "short": [[1], [3, 4]]}
    bad = []
    for edit, runs_want in want.items():
        folder = SCRATCH / "gaps" / edit
        if folder.exists():
            shutil.rmtree(folder)
        write_gap_recording(folder, edit)
        warnings: list[str] = []
        sink = logger.add(lambda m: warnings.append(str(m)), level="WARNING")
        try:
            rec = open_recording(folder)
            runs = plan_runs(recording_files(rec, ".td_150"), 150.0)
        except Exception as exc:  # the code before the fix refuses: a failure, not a crash
            bad.append(f"{edit}: {type(exc).__name__}: {exc}")
            continue
        finally:
            logger.remove(sink)
        got = [r.sequences for r in runs]
        if got != runs_want:
            bad.append(f"{edit}: runs {got}, expected {runs_want}")
        for k, run in enumerate(runs):
            per_folder = {f: [p.sequence for p in files] for f, files in run.files.items()}
            if sorted(per_folder) != sorted(RECEIVERS["MTU8"][2]) or len({tuple(v) for v in per_folder.values()}) != 1:
                bad.append(f"{edit} run {k + 1}: sequences per folder {per_folder}")
            if any(p.path.stat().st_size <= 128 for files in run.files.values() for p in files):
                bad.append(f"{edit} run {k + 1}: an empty file in the plan")
        notes = [getattr(r, "notes", []) for r in runs]
        if len(runs_want) == 1:
            if any(notes):
                bad.append(f"{edit}: gap notes {notes} on a recording without a gap")
        else:
            second = " ".join(notes[1]) if len(notes) > 1 else ""
            if not ("phoenix_gap" in second and "sequence 2" in second and f"folder {GAP_FOLDER}" in second
                    and "360 s" in second) or notes[0]:
                bad.append(f"{edit}: gap notes {notes}, expected one on run 2 naming sequence 2, folder "
                           f"{GAP_FOLDER} and 360 s")
        empties = (["_00000005.td_150"] * 4 if edit == "trailing_empty" else
                   [f"_{GAP_FOLDER}_00000002.td_150"] if edit == "empty" else [])
        named = [w for w in warnings if "0 bytes" in w]
        if len(named) != len(empties) or not all(any(e in w for w in named) for e in empties):
            bad.append(f"{edit}: warnings naming empty files {named}, expected {len(empties)} naming {set(empties)}")
    return bad


CAL_EPOCHS = (0x5FA23A8E, 0x6088C699, 0x60ADD551)  # 4 Nov 2020, 28 Apr 2021, 26 May 2021 (UTC)
SAME_DAY = (0x60ADD560, 0x60ADD7D5)  # two receiver files ten minutes apart on 26 May 2021


def write_scal(folder: Path, serial: str, epoch: int) -> Path:
    """Write a minimal EMpower-form coil table ``<serial>_<epoch hex>.scal.json`` (two points)."""
    path = folder / f"{serial}_{epoch:08X}.scal.json"
    path.write_text(json.dumps({
        "file_type": "sensor calibration", "inst_serial": "10240", "instrument_type": "MTU-5C",
        "instrument_model": "RMT03-D", "sensor_serial": serial, "timestamp_utc": epoch,
        "cal_data": [{"tag": "H1", "num_of_responses": 1, "chan_data": [
            {"num_records": 2, "freq_Hz": [1.0, 10.0], "magnitude": [20.0, 27.0], "phs_deg": [80.0, 10.0]}]}]}))
    return path


def check_calibration_dates() -> list[str]:
    """Check the calibration-date rule of `mt_workbench.phoenix` on synthetic calibration folders."""
    from types import SimpleNamespace

    import mt_workbench.phoenix as phoenix

    folder = SCRATCH / "calibrations"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    three = [write_scal(folder, "50001", e) for e in CAL_EPOCHS]
    one = write_scal(folder, "50002", CAL_EPOCHS[1])
    for epoch in (CAL_EPOCHS[0], *SAME_DAY):
        (folder / f"10999_{epoch:08X}.rxcal.json").write_text("{}")
    rec = SimpleNamespace(receiver="10999")
    day = 86400
    cases = [  # (what, start, expected file)
        ("coil before the first", CAL_EPOCHS[0] - 3 * day, three[0]),
        ("coil between two", CAL_EPOCHS[1] + 2 * day, three[1]),
        ("coil on an epoch", CAL_EPOCHS[1], three[1]),
        ("coil hours after an epoch", CAL_EPOCHS[1] + 5 * 3600, three[1]),
        ("coil after the last", CAL_EPOCHS[2] + 60 * day, three[2]),
        ("coil with one file, before", CAL_EPOCHS[1] - 30 * day, one),
        ("coil with one file, after", CAL_EPOCHS[1] + 30 * day, one),
        ("receiver between same-day files", SAME_DAY[0] + 60, folder / f"10999_{SAME_DAY[0]:08X}.rxcal.json"),
        ("receiver after both same-day files", SAME_DAY[1] + day, folder / f"10999_{SAME_DAY[1]:08X}.rxcal.json"),
        ("receiver before the second date", CAL_EPOCHS[1], folder / f"10999_{CAL_EPOCHS[0]:08X}.rxcal.json"),
    ]
    bad = []
    for what, start, expected in cases:
        if what.startswith("coil"):
            serial = expected.name.split("_")[0]
            stage, got, _on = phoenix._coil_stage(serial, folder, float(start))
            if stage is None or stage.name != f"{phoenix.COIL_PREFIX}{serial}":
                bad.append(f"{what}: stage {stage}")
        else:
            got = phoenix._rxcal(rec, folder, float(start))
        if got != expected:
            bad.append(f"{what}: {got.name if got else None}, expected {expected.name}")
    if phoenix._coil_stage("50003", folder, float(CAL_EPOCHS[1])) != (None, None, None):
        bad.append("coil with no file: not (None, None, None)")
    try:
        phoenix._rxcal(SimpleNamespace(receiver="10998"), folder, float(CAL_EPOCHS[1]))
        bad.append("receiver with no file: no FileNotFoundError")
    except FileNotFoundError:
        pass
    try:
        phoenix._coil_stage("50001", folder, None)
        bad.append("several files and no start: not refused")
    except ValueError:
        pass
    if phoenix.calibration_date(three[1]) != "2021-04-28":
        bad.append(f"calibration_date {phoenix.calibration_date(three[1])}, expected 2021-04-28")
    shutil.rmtree(folder)
    return bad


def reversed_rule(found: list, start_s, what: str) -> Path:
    """The date rule reversed (the mutation): the earliest at or after the start, else the latest before."""
    import mt_workbench.phoenix as phoenix

    if len(found) == 1:
        return Path(found[0])
    if start_s is None:
        raise ValueError(f"{what}: no start")
    dated = sorted((phoenix.calibration_epoch(f), Path(f)) for f in found)
    after = [f for e, f in dated if e >= start_s]
    return after[0] if after else dated[-1][1]


def warnings_of(call) -> tuple[object, list[str]]:
    """Return `call()`'s result and the warning lines loguru logged during it."""
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lambda m: lines.append(m.record["message"]), level="WARNING", format="{message}")
    try:
        return call(), lines
    finally:
        logger.remove(sink)


def check_after_start_warning() -> list[str]:
    """Check the warning `calibration_for` logs when it takes a file dated after the recording's start."""
    import mt_workbench.phoenix as phoenix

    folder = SCRATCH / "calibrations_after"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    three = [write_scal(folder, "50001", e) for e in CAL_EPOCHS]
    one = write_scal(folder, "50002", CAL_EPOCHS[1])
    day = 86400
    bad = []
    cases = [  # (what, serial, start, expected file, expected days or None for no warning)
        ("three files, start before the first", "50001", CAL_EPOCHS[0] - 3 * day, three[0], 3.0),
        ("one file, start before it", "50002", CAL_EPOCHS[1] - 30 * day, one, 30.0),
        ("three files, start between two", "50001", CAL_EPOCHS[1] + 2 * day, three[1], None),
        ("one file, start after it", "50002", CAL_EPOCHS[1] + 30 * day, one, None),
    ]
    for what, serial, start, expected, days in cases:
        (stage, got, _on), lines = warnings_of(lambda: phoenix._coil_stage(serial, folder, float(start)))
        if got != expected:
            bad.append(f"{what}: took {got.name if got else None}, expected {expected.name}")
        if days is None:
            if lines:
                bad.append(f"{what}: a warning where a file at or before the start exists: {lines}")
            continue
        hits = [x for x in lines if f"coil {serial}" in x and expected.name in x and f"{days:.1f} days after" in x]
        if len(hits) != 1:
            bad.append(f"{what}: {len(hits)} warning(s) naming coil {serial}, {expected.name} and {days:.1f} days "
                       f"after; logged {lines}")
    shutil.rmtree(folder)
    return bad


def write_rxcal(folder: Path, receiver: str, epoch: int, curve_from: str | None) -> Path:
    """Write a stand-in ``<receiver>_<epoch hex>.rxcal.json``, converted (`curve_below_records_from`) or not."""
    path = folder / f"{receiver}_{epoch:08X}.rxcal.json"
    body = {"file_type": "receiver calibration", "inst_serial": receiver, "timestamp_utc": epoch, "cal_data": []}
    if curve_from is not None:
        body.update(converted_from=path.name[:-5], curve_below_records_from=curve_from)
    path.write_text(json.dumps(body))
    return path


def check_rxcal_comment() -> list[str]:
    """Check the date part of the rxcal comment piece for an EMpower and a converted receiver file."""
    import mt_workbench.phoenix as phoenix

    folder = SCRATCH / "calibrations_rxcal"
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    empower = write_rxcal(folder, "10307", 0x5FA205AE, None)
    converted = write_rxcal(folder, "10307", 0x60ADCE5D, empower.name)
    cases = [  # (what, file, low pass, expected)
        ("EMpower file", empower, 10000, "calibrated 2020-11-04"),
        ("converted file, lp 10000", converted, 10000,
         "records calibrated 2021-05-26; curve below 1024 Hz from 10307_5FA205AE.rxcal.json"),
        ("converted file, lp 10", converted, "10", "records calibrated 2021-05-26; curve below 0.2 Hz from "
                                                   "10307_5FA205AE.rxcal.json"),
        ("converted file, unknown lp", converted, 5000,
         "records calibrated 2021-05-26; curve below the records from 10307_5FA205AE.rxcal.json"),
    ]
    bad = []
    for what, path, lp, expected in cases:
        got = phoenix._rxcal_dates(path, lp)
        if got != expected:
            bad.append(f"{what}: {got!r}, expected {expected!r}")
    shutil.rmtree(folder)
    return bad


def check_new_survey(root: Path, mutate: bool = False) -> list[str]:
    """Run scripts/new_survey.py on the Phoenix folders and check the survey it writes.

    With `mutate`, its Phoenix defaults are left out (the check must fail).
    """
    import contextlib
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("new_survey", REPO / "scripts" / "new_survey.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if mutate:
        module.phoenix_defaults = lambda head: head
    phoenix_only = SCRATCH / "phoenix_root"
    if phoenix_only.exists():
        shutil.rmtree(phoenix_only)
    for site in RECEIVERS:
        shutil.copytree(root / site, phoenix_only / site)
    rsp = phoenix_only.parent / "coil.rsp"
    rsp.write_text("0.1 1.0 0.0\n")
    out = phoenix_only.parent / "survey" / "survey.yaml"
    with contextlib.redirect_stdout(io.StringIO()):
        code = module.main([str(phoenix_only), "--name", "PHX", "--instrument", "phoenix", "--out", str(out),
                            "--calibration", str(rsp), "--force"])
    if code not in (0, None):
        return [f"new_survey.py exit {code}"]
    survey = Survey.from_yaml(out)
    bad = []
    for site, (receiver, _model, _mapping) in RECEIVERS.items():
        cfg = survey.site(site)
        got = (cfg.serial, cfg.dipole_length_ex, cfg.dipole_length_ey, cfg.calibration_dir)
        if got != (receiver, 0.0, 0.0, "sensors"):
            bad.append(f"{site}: serial, dipoles, calibration_dir {got}")
    if abs(float(survey.processing["min_period"]) - 4 ** (22 / 6) / 6000) > 1e-15:
        bad.append(f"min_period {survey.processing['min_period']!r}")
    return bad


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    root = build_root()
    check_names(root)
    check_detection(root)
    bad = check_starts(root)
    assert not bad, bad
    print(f"  file_start: recording id - {LEAP} s, + 1 s (sequence 1) or + 360 s x (sequence - 1); bursts at "
          f"their stamp - {LEAP} s")
    check_listing(root)
    kept = instruments.gps_to_utc_seconds
    instruments.gps_to_utc_seconds = lambda s: int(s)  # mutation: no leap seconds
    try:
        tripped = check_starts(root)
    finally:
        instruments.gps_to_utc_seconds = kept
    assert tripped and all("+18 s" in t for t in tripped), tripped
    print(f"  mutation (no leap seconds) tripped {len(tripped)} file starts, each +18 s")
    bad = check_new_survey(root)
    assert not bad, bad
    print("  new_survey.py: serial per receiver, dipoles 0.0, calibration_dir sensors, min_period 4**(22/6)/6000")
    trip = check_new_survey(root, mutate=True)
    assert trip, "mutation (no Phoenix defaults) did not trip"
    print(f"  mutation (new_survey.py without the Phoenix defaults) tripped: {trip[0]}")
    bad = check_gaps()
    for line in bad:
        print(f"  FAIL gaps: {line}")
    assert not bad, f"{len(bad)} gap case failure(s)"
    print(f"  gaps: equal folders and a trailing 0-byte sequence one run 1-4 (four empty files named); sequence 2 "
          f"missing, 0 bytes or 60 s short in folder {GAP_FOLDER}: runs 1 and 3-4 in every folder, the gap note "
          f"on run 2 (sequence 2, folder {GAP_FOLDER}, 360 s)")
    import mt_workbench.phoenix as phoenix
    kept = phoenix._aligned_files
    phoenix._aligned_files = lambda files: (files, [])  # mutation: each folder's own files, as read_sequence
    try:
        trip = check_gaps()
    finally:
        phoenix._aligned_files = kept
    assert any(t.startswith("missing") for t in trip), trip
    print(f"  mutation (each folder's own files) tripped: {next(t for t in trip if t.startswith('missing'))}")
    bad = check_calibration_dates()
    for line in bad:
        print(f"  FAIL calibration dates: {line}")
    assert not bad, f"{len(bad)} calibration-date case failure(s)"
    print("  calibration dates: earliest before the first, latest at or before the start between and after, the "
          "day's file on and after its epoch, one file always, same-day receiver files by the minute, none for no "
          "file, refused with no start")
    kept = phoenix.calibration_for
    phoenix.calibration_for = reversed_rule  # mutation: the rule reversed
    try:
        trip = check_calibration_dates()
    finally:
        phoenix.calibration_for = kept
    # before the first and after the last, the reversed rule's fallback gives the same file
    assert any(t.startswith("coil between two") for t in trip) and any(
        t.startswith("receiver between same-day files") for t in trip), trip
    print(f"  mutation (rule reversed) tripped {len(trip)} case(s): {trip[0]}")
    bad = check_after_start_warning()
    for line in bad:
        print(f"  FAIL after-start warning: {line}")
    assert not bad, f"{len(bad)} after-start warning failure(s)"
    print("  after-start warning: one line naming the coil, the file and 3.0 or 30.0 days, the choice unchanged; "
          "none with a file at or before the start")
    kept = phoenix._warn_after_start
    phoenix._warn_after_start = lambda *args: None  # mutation: no warning
    try:
        trip = check_after_start_warning()
    finally:
        phoenix._warn_after_start = kept
    assert sum("warning(s) naming" in t for t in trip) == 2, trip
    print(f"  mutation (no warning) tripped {len(trip)} case(s): {trip[0]}")
    bad = check_rxcal_comment()
    for line in bad:
        print(f"  FAIL rxcal comment: {line}")
    assert not bad, f"{len(bad)} rxcal comment failure(s)"
    print("  rxcal comment: 'calibrated 2020-11-04' for the EMpower file; 'records calibrated 2021-05-26; curve "
          "below 1024 Hz from 10307_5FA205AE.rxcal.json' for the converted one at lp 10000 (0.2 Hz at lp 10, "
          "'the records' at lp 5000)")
    kept = phoenix._rxcal_dates
    phoenix._rxcal_dates = lambda rxcal, lp=None: f"calibrated {phoenix.calibration_date(rxcal)}"  # mutation
    try:
        trip = check_rxcal_comment()
    finally:
        phoenix._rxcal_dates = kept
    assert len(trip) == 3 and all(t.startswith("converted") for t in trip), trip
    print(f"  mutation (the date alone, no curve clause) tripped {len(trip)} case(s): {trip[0]}")
    shutil.rmtree(root)
    shutil.rmtree(SCRATCH / "gaps")
    print("\nPASS  phoenix_files_unit")
