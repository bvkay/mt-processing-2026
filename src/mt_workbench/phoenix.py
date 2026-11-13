# -*- coding: utf-8 -*-
"""
Phoenix MTU-5C and MTU-8A recordings read through mt-io into runs

A Phoenix receiver writes one folder per recording: the receiver metadata
(empower_recmeta.json, written by EMpower after the survey, and the
receiver's own recmeta.json), config.json, backend.log, and one numbered
folder per channel input. Each channel folder holds the continuous files
(`.td_150`, `.td_30`, a fragment of 360 s or 600 s each) and the 24 kHz
burst files (`.td_24k`), named
``<receiver>_<recording id hex>_<channel>_<sequence hex>.<ext>``.

The files are read by mt-io's Phoenix readers. mt-io picks the metadata
file (empower_recmeta.json first, `phoenix_metadata_file`) and takes from
it the channel map (folder index to E1 E2 H1 H2 H3, different on the
MTU-5C and the MTU-8A), the coil serial and the dipole length. This module
adds what mt-workbench needs on top:

- the recordings of a site folder (`find_recordings`) and their files,
  listed from the 128-byte headers (`recording_files`), a file of no more
  than its header (a 0-byte last file) skipped with a warning;
- runs: the continuous files are read one by one with
  `open_phoenix(fn).read()` and joined where each file starts at the end
  of the one before (`plan_runs`); a file that does not meet its
  predecessor (a short or missing file) starts a new run. A sequence that
  one channel folder lacks, holds empty or holds with another sample
  count is left out of every channel (`_aligned_files`), so the run
  before it ends and the next starts after it, the channels stay aligned
  and no sample is filled in; the seconds left out are logged and written
  in a "phoenix_gap" line of the run comment. mt-io's `read_sequence`
  joins a folder's files with no time check;
- the input rail of each channel, 0.9 x the input range of its file
  header (`input_range_v`), which the dc level record measures against;
- the receiver's channel names renamed to ex ey hx hy hz (`RENAME`), and
  at a site declared `swap_e` the E2 input stored as ex and the E1 input
  as ey, each with everything read from its input (`component_of`);
- the second by which the stamps of file version 2 trail GPS
  (`STAMP_CORRECTION_S`, Phoenix DAA09), added to every run start of such
  a file after checking that mt-io's start is the one its own arithmetic
  gives (`stamp_correction`), so that a reader that already corrects it
  is not corrected twice. It is recorded under its own comment key
  (`archive_stamp_correction`), apart from a site's `clock_offset_s`;
- each channel's calibration chain from the field to the recorded volts
  (`_channel_chain`), in the order mt_metadata and aurora divide by:
  ex, ey: the dipole (mV/km to mV), `MV_TO_V` (mV to V), the receiver's
  curve (V to V); hx, hy, hz: the coil table named by the coil's serial
  (`COIL_PREFIX`, nT to mV), the H input polarity (`H_POLARITY`, mV to
  mV, gain -1), `MV_TO_V`, the receiver's curve. mt-io's
  chain carries a `v_to_mv` stage of gain 1000 where the divide needs
  1/1000, so that calibrated E and H come out 10^6 too small; it is
  replaced, after checking that it is that stage. mt-io reads no coil
  response (`get_sensor_filter` is a stub), so the coil's
  ``<serial>_*.scal.json`` is attached here. The Phoenix records H with
  the sign of the LEMI-423's recorded H (the stored volts and counts are
  in phase); mt-workbench's convention (lemimt's, the LEMI-423 chain's
  `lemi423_b_scale` of gain -1000) negates H, and the polarity stage puts
  the Phoenix H into it (`_h_polarity_stage`). The samples stay as
  recorded. An archive built before the stage is found by
  `archive_h_polarity` (`warn_without_h_polarity` logs it). Where a coil
  or receiver has several calibration files, the latest dated (the hex
  epoch of its name) at or before the recording's start is taken, else
  the earliest after it with a warning (`calibration_for`); the file and
  its date go into the channel comment, and for a receiver file converted
  from the binary form, the file its curve below the measured records
  came from;
- the coil serial and dipole length: mt-io's, from the metadata file it
  takes, unless survey.yaml declares `coil_hx`/`coil_hy`/`coil_hz` or a
  non-zero `dipole_length_ex`/`dipole_length_ey`; recmeta.json's values
  and the coil's own report in backend.log (`coil_self_reports`) are
  recorded beside them;
- the run, channel and station comments naming the receiver, the
  recording, the metadata file, the sources of every coil and dipole, and
  the correction;
- the 24 kHz bursts (`.td_24k`, 2 s every 30 s or 1 s every 60 s): every
  burst of a file is read through mt-io's `DecimatedSegmentCollection` on
  a fresh reader (`_read_bursts`; the installed mt-io's `read_phoenix`
  returns the first burst only), checked against a walk of the file's
  sub-headers (`burst_index`), and the channel folders' bursts are matched
  by stamp (`burst_slots`). `mt_workbench.ingest` writes one run per burst.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

from .instruments import (
    PHOENIX_CONTINUOUS, PHOENIX_HEADER_BYTES, PHOENIX_METADATA, PHOENIX_MODELS, PHOENIX_UNREAD,
    gps_to_utc_seconds, is_record, phoenix_file_start, phoenix_header, phoenix_metadata_file,
)

# the seconds by which the time stamps of Phoenix files of version below STAMP_CORRECTED_BELOW trail
# GPS (Phoenix DAA09), added to every time stamp read from such a file
STAMP_CORRECTION_S = 1.0
STAMP_CORRECTED_BELOW = 3
# start of the line recording the correction in the run, channel and station comments, followed by
# its value in seconds; one "key: value" piece with no dot in the key and no semicolon (the EMTF XML
# writer splits run comments on ";")
_STAMP_PREFIX = "phoenix_stamp_correction_s: "
# the receiver's channel tags as mt-io names them, and the names mt-workbench stores
RENAME = {"e1": "ex", "e2": "ey", "h1": "hx", "h2": "hy", "h3": "hz"}
# the names the two electric inputs are stored under at a site declared `swap_e` (`component_of`)
SWAP_E = {"e1": "ey", "e2": "ex"}
# a start that differs from mt-io's own file arithmetic by more than this is refused, in seconds
_STAMP_TOLERANCE_S = 1e-6
# a file joins the run before it when it starts within this many samples of that run's end
_JOIN_TOLERANCE_SAMPLES = 0.5
# the stage that turns the receiver's recorded volts into the millivolts the coil and dipole stages
# give: mV in, V out, gain 1/1000. It takes the place of mt-io's `v_to_mv` (V in, mV out, gain 1000)
MV_TO_V = "phoenix_mv_to_v"
# mt-io's stage it replaces, and that stage's gain
MTIO_V_TO_MV = "v_to_mv"
MTIO_V_TO_MV_GAIN = 1000.0
# the name of a coil's response stage: the prefix and the coil's serial alone (the scal file's own
# name carries the receiver the coil was calibrated on, which is not the one it recorded on)
COIL_PREFIX = "phoenix_coil_"
# a declared dipole length that differs from the metadata file's by more than this is logged, in m
DIPOLE_DIFF_M = 0.5
# a coil's report of its serial in the receiver's backend.log, with the channel folder index
_SELF_REPORT = re.compile(r"Sensor Message \(Ch(\d+)\):.*\bSE(\d+)[A-Z]?\s*$")
# the stage on every magnetic channel (hx, hy, hz) that puts the Phoenix H into mt-workbench's polarity
# convention, and its gain; mV in, mV out, between the coil stage and `MV_TO_V` (`_h_polarity_stage`)
H_POLARITY = "phoenix_h_polarity"
H_POLARITY_GAIN = -1.0
H_POLARITY_COMMENT = ("Phoenix H into mt-workbench's (LEMI-423 chain's) polarity convention; "
                      "docs/upstream_issues.md 81")
# the run comment's note on the replaced units stage
UNITS_NOTE = (f"phoenix_units: mt-io {MTIO_V_TO_MV} (gain {MTIO_V_TO_MV_GAIN:g}) replaced by {MV_TO_V} "
              f"(gain {1 / MTIO_V_TO_MV_GAIN:g}), calibrated E in mV/km and H in nT")


def component_of(tag: str, swap_e: bool = False) -> str:
    """Return the name a receiver input's samples are stored under.

    The tag of the metadata file's channel map renamed (`RENAME`). At a
    site declared `swap_e`, whose two electric lines were connected to
    each other's inputs, the E2 input is stored as ex and the E1 input as
    ey (`SWAP_E`). Everything the reader takes from an input goes with its
    samples under that name: the receiver curve (the
    ``..._e2_..._lowpass`` stage under ex), the rail, the contact readings,
    the metadata file's dipole length, the folder number and the
    "phoenix: folder 7, tag E2" comment; the dipole length and azimuth
    survey.yaml declares are the stored channel's (`_channel_chain`).

    Args:
        tag (str): The input's tag, lower case (e1 e2 h1 h2 h3).
        swap_e (bool): Whether the site declares `swap_e`.

    Returns:
        str: The stored channel name.
    """
    if swap_e and tag in SWAP_E:
        return SWAP_E[tag]
    return RENAME.get(tag, tag)


def swap_e_piece(tag: str, comp: str, azimuth: float) -> str:
    """Return the channel comment piece of an electric input stored under the other name (`component_of`)."""
    # one "key: value" piece with no semicolon (the EMTF XML writer splits comments on ";")
    return (f"swap_e: the {tag.upper()} input stored as {comp}, with its samples, receiver curve, contact "
            f"readings and rail, at azimuth {azimuth:g} deg and the dipole length of survey.yaml")


@dataclass
class PhoenixRecording:
    """One recording folder of a Phoenix receiver.

    Attributes:
        path (Path): The folder holding the channel folders.
        meta_path (Path): The receiver metadata file mt-io takes.
        meta (dict): That file, parsed.
        recmeta (dict or None): recmeta.json, parsed, when mt-io took
            empower_recmeta.json and recmeta.json is present too.
        receiver (str): The receiver id (``instid``).
        receiver_model (str): The model code (RMT03-D, RMT03-G, RMT05).
        model (str): MTU-5C or MTU-8A.
        tags (dict): Channel folder index to the tag of the metadata file's
            channel map, lower case (e1 e2 h1 h2 h3), for the folders that
            hold files.
    """

    path: Path
    meta_path: Path
    meta: dict
    recmeta: dict | None
    receiver: str
    receiver_model: str
    model: str
    tags: dict = field(default_factory=dict)

    @property
    def recording_id(self) -> str:
        """The recording id as the file names write it (8 hex digits)."""
        first = next(f for f in sorted(self.path.glob("*/*")) if is_record(f, "phoenix"))
        return first.stem.split("_")[1]

    @property
    def start_s(self) -> float:
        """The recording's start, UTC seconds: its id (GPS seconds) less the leap seconds."""
        return float(gps_to_utc_seconds(int(self.recording_id, 16)))

    def chan(self, tag: str, meta: dict | None = None) -> dict:
        """Return a channel's entry of a metadata file's ``chconfig.chans``, {} when absent."""
        meta = self.meta if meta is None else meta
        for entry in (meta or {}).get("chconfig", {}).get("chans", []):
            if str(entry.get("tag", "")).lower() == tag.lower():
                return entry
        return {}


@dataclass
class PhoenixFile:
    """One Phoenix data file, from its header.

    Attributes:
        path (Path): The file.
        folder (int): Channel folder index.
        sequence (int): File sequence number.
        version (int): File format version.
        rate (float): Sample rate in Hz.
        n (int): Samples ((size - 128) / 4) of a continuous file.
        start_s (float): UTC time of the first sample as mt-io dates it,
            without `STAMP_CORRECTION_S`.
    """

    path: Path
    folder: int
    sequence: int
    version: int
    rate: float
    n: int
    start_s: float

    @property
    def end_s(self) -> float:
        """The time just after the last sample, as mt-io dates the file."""
        return self.start_s + self.n / self.rate


@dataclass
class RunPlan:
    """The files of one run of a recording, the same sequence numbers in every channel folder.

    Attributes:
        files (dict): Folder index to its PhoenixFile list, in sequence order.
        notes (list of str): Run comment lines on the sequences left out
            next to the run ("phoenix_gap: ..."), from `plan_runs`.
    """

    files: dict
    notes: list = field(default_factory=list)

    @property
    def sequences(self) -> list[int]:
        """The run's file sequence numbers."""
        return [f.sequence for f in next(iter(self.files.values()))]

    @property
    def start_s(self) -> float:
        """The run's first sample as mt-io dates it."""
        return next(iter(self.files.values()))[0].start_s

    @property
    def n(self) -> int:
        """Samples per channel."""
        return int(sum(f.n for f in next(iter(self.files.values()))))


def find_recordings(site_dir: Path, recording: str | None = None) -> list[Path]:
    """Return the recording folders of a Phoenix site folder.

    A recording folder holds a receiver metadata file (`PHOENIX_METADATA`)
    beside numbered channel folders with Phoenix data files.

    Args:
        site_dir (Path): The site folder.
        recording (str, optional): The site's `recording` key: one folder,
            relative to the site folder ("." for the site folder itself).

    Returns:
        list of Path: The recording folders, sorted by name.

    Raises:
        FileNotFoundError: If the declared folder is not a recording, or
            the site folder holds none.
    """
    site_dir = Path(site_dir)

    def is_recording(d: Path) -> bool:
        if not any((d / name).is_file() for name in PHOENIX_METADATA):
            return False
        return any(c.is_dir() and c.name.isdigit() and any(is_record(f, "phoenix") for f in c.iterdir())
                   for c in d.iterdir())

    if recording is not None:
        folder = (site_dir / recording).resolve()
        if not folder.is_dir() or not is_recording(folder):
            raise FileNotFoundError(f"{site_dir.name}: recording {recording!r} ({folder}) is not a Phoenix "
                                    f"recording folder: no {' or '.join(PHOENIX_METADATA)} beside numbered "
                                    f"channel folders of Phoenix files")
        return [folder]
    found = [site_dir] if is_recording(site_dir) else []
    found += sorted(d for d in site_dir.rglob("*") if d.is_dir() and not d.name.isdigit() and is_recording(d))
    if not found:
        raise FileNotFoundError(f"{site_dir}: no Phoenix recording folder (a {' or '.join(PHOENIX_METADATA)} "
                                f"beside numbered channel folders of Phoenix files)")
    return found


def open_recording(path: Path) -> PhoenixRecording:
    """Read a recording folder's metadata, as mt-io's readers will take it.

    Args:
        path (Path): A recording folder (`find_recordings`).

    Returns:
        PhoenixRecording: The recording.

    Raises:
        FileNotFoundError: If it holds no receiver metadata file.
    """
    path = Path(path)
    meta_path = phoenix_metadata_file(path)
    if meta_path is None:
        raise FileNotFoundError(f"{path}: no {' or '.join(PHOENIX_METADATA)}: mt-io would read the channels "
                                f"with its default channel map, which is wrong for the MTU-5C and the MTU-8A")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    other = path / "recmeta.json"
    recmeta = (json.loads(other.read_text(encoding="utf-8"))
               if meta_path.name != "recmeta.json" and other.is_file() else None)
    code = (meta.get("channel_map") or {}).get("receiver_model") or meta.get("receiver_model") or ""
    mapping = {int(m["idx"]): str(m["tag"]).lower() for m in (meta.get("channel_map") or {}).get("mapping", [])}
    folders = sorted(int(c.name) for c in path.iterdir() if c.is_dir() and c.name.isdigit()
                     and any(is_record(f, "phoenix") for f in c.iterdir()))
    missing = [i for i in folders if i not in mapping]
    if missing:
        raise ValueError(f"{path}: channel folder(s) {missing} not in {meta_path.name}'s channel map {mapping}")
    return PhoenixRecording(path=path, meta_path=meta_path, meta=meta, recmeta=recmeta,
                            receiver=str(meta.get("instid", "")), receiver_model=code,
                            model=PHOENIX_MODELS.get(code, meta.get("receiver_commercial_name") or code),
                            tags={i: mapping[i] for i in folders})


def recording_files(rec: PhoenixRecording, suffix: str) -> dict[int, list[PhoenixFile]]:
    """List a recording's files of one type, per channel folder, from their headers.

    Args:
        rec (PhoenixRecording): The recording.
        suffix (str): A file type, such as ".td_150" or ".td_24k".

    A file of no more than its 128-byte header (the receiver leaves a
    0-byte last file when it stops) holds no sample: it is skipped with a
    warning naming it, so that its sequence is missing from that folder
    (`plan_runs`).

    Returns:
        dict: Channel folder index to its files in sequence order; folders
        with no file of the type are left out.

    Raises:
        ValueError: If a file's header names another receiver, channel
            folder or recording than its name and folder, or every file
            of the type in a folder is empty.
    """
    out: dict[int, list[PhoenixFile]] = {}
    for folder in rec.tags:
        files, empty = [], []
        for path in (rec.path / str(folder)).iterdir():
            if path.suffix.lower() != suffix or not is_record(path, "phoenix"):
                continue
            size = path.stat().st_size
            if size <= PHOENIX_HEADER_BYTES:
                logger.warning(f"{path.name}: {size} bytes, no sample past the {PHOENIX_HEADER_BYTES}-byte header: "
                               f"skipped")
                empty.append(path.name)
                continue
            head = phoenix_header(path)
            receiver, rec_hex, channel, _seq = path.stem.split("_")
            if (head["channel"], head["recording_id"]) != (folder, int(rec_hex, 16)) or int(channel) != folder:
                raise ValueError(f"{path}: header channel {head['channel']} recording {head['recording_id']:08X} "
                                 f"does not match its name and folder {folder}")
            if head["receiver"] and head["receiver"] != receiver:
                raise ValueError(f"{path}: header receiver {head['receiver']} does not match its name")
            n = (path.stat().st_size - PHOENIX_HEADER_BYTES) // 4 if suffix in PHOENIX_CONTINUOUS else 0
            files.append(PhoenixFile(path=path, folder=folder, sequence=int(head["sequence"]),
                                     version=int(head["file_version"]), rate=float(head["sample_rate"]), n=int(n),
                                     start_s=phoenix_file_start(head, suffix)))
        if empty and not files:
            raise ValueError(f"{rec.path / str(folder)}: every {suffix} file is empty ({', '.join(sorted(empty))}): "
                             f"the channel would be left out of the runs")
        if files:
            out[folder] = sorted(files, key=lambda f: f.sequence)
    return out


def unread_types(rec: PhoenixRecording) -> list[str]:
    """Return the file types of a recording that mt-io has no reader for (`PHOENIX_UNREAD`)."""
    found = {p.suffix.lower() for c in rec.tags for p in (rec.path / str(c)).iterdir()}
    return [s for s in PHOENIX_UNREAD if s in found]


def input_range_v(path: Path) -> float:
    """Return a channel's input range in V from a Phoenix file's header.

    It is the converter's range over the board's total circuitry gain
    (mt-io's `Header.ad_plus_minus_range / total_circuitry_gain`, the
    range mt-io's `NativeReader` scales input volts by): 2.5 V for an E
    channel at gain 2 and 1.25 V for an H channel at gain 4. The stored
    samples are input volts, so a sample at the converter's rail is at
    this level.

    Args:
        path (Path): A Phoenix data file of the channel.

    Returns:
        float: The input range in V.
    """
    from mt_io.phoenix.readers.header import Header

    header = Header()
    with open(path, "rb") as stream:
        header.unpack_header(stream)
    return float(header.ad_plus_minus_range) / float(header.total_circuitry_gain)


def _check_rates(files: dict[int, list[PhoenixFile]], rate: float) -> None:
    """Refuse a file whose header rate is not the site's declared rate.

    Raises:
        ValueError: Naming the first such file.
    """
    for mine in files.values():
        wrong = [f for f in mine if abs(f.rate - rate) > 1e-9 * rate]
        if wrong:
            raise ValueError(f"{wrong[0].path.name}: {wrong[0].rate:g} Hz in its header; the site is declared at "
                             f"{rate:g} Hz (sample_rate)")


def _folders_text(folders) -> str:
    """Return "folder 3" or "folders 0 2 7"."""
    folders = list(folders)
    return f"folder{'s' if len(folders) > 1 else ''} {' '.join(str(f) for f in folders)}"


def _aligned_files(files: dict[int, list[PhoenixFile]]) -> tuple[dict[int, list[PhoenixFile]], list[dict]]:
    """Keep the sequences that every channel folder holds with one sample count.

    A sequence that some folder lacks (never written, or skipped by
    `recording_files` as empty) or holds with another sample count is
    left out of every folder, so that the k-th file of each folder is the
    same recorded time; no sample is filled in.

    Args:
        files (dict): `recording_files` of one continuous type.

    Returns:
        tuple: (folder index to its kept files in sequence order; per
        sequence left out a dict of ``sequence``, ``start_s`` and
        ``end_s`` as the folders holding it date it, and ``why``).
    """
    folders = sorted(files)
    by_folder = {f: {p.sequence: p for p in files[f]} for f in folders}
    kept: dict[int, list[PhoenixFile]] = {f: [] for f in folders}
    dropped = []
    for seq in sorted(set().union(*by_folder.values())):
        held = {f: by_folder[f][seq] for f in folders if seq in by_folder[f]}
        counts: dict[int, list[int]] = {}
        for f, pf in held.items():
            counts.setdefault(pf.n, []).append(f)
        if len(held) == len(folders) and len(counts) == 1:
            for f, pf in held.items():
                kept[f].append(pf)
            continue
        first = next(iter(held.values()))
        why, lacking = [], [f for f in folders if f not in held]
        if lacking:
            receiver, rec_hex, _channel, seq_hex = first.path.stem.split("_")
            empty = [f for f in lacking if (first.path.parent.parent / str(f) /
                                            f"{receiver}_{rec_hex}_{f}_{seq_hex}{first.path.suffix}").is_file()]
            absent = [f for f in lacking if f not in empty]
            why += [f"not in {_folders_text(absent)}"] if absent else []
            why += [f"empty in {_folders_text(empty)}"] if empty else []
        if len(counts) > 1:
            why.append("samples " + " against ".join(f"{n} in {_folders_text(fs)}" for n, fs in sorted(counts.items())))
        dropped.append(dict(sequence=seq, start_s=first.start_s, end_s=max(p.end_s for p in held.values()),
                            why=", ".join(why)))
    return kept, dropped


def _gap_notes(plans: list[RunPlan], dropped: list[dict], t0: float, t1: float, name: str) -> None:
    """Write a "phoenix_gap" note on the run next to each group of sequences left out, and log it.

    The note goes on the run after the group, or on the last run for a
    group after it; it names each sequence and why it was left out, and
    the seconds between the two runs' samples (for a group before the
    first run or after the last, the seconds its files span beyond it).

    Args:
        plans (list of RunPlan): The runs, in time order; notes are added.
        dropped (list of dict): `_aligned_files`'s sequences left out.
        t0 (float): Window start, UTC seconds (-inf for none).
        t1 (float): Window end, UTC seconds (inf for none).
        name (str): The recording folder's name, for the log.
    """
    groups: dict[int, list[dict]] = {}
    for gap in dropped:
        if gap["start_s"] < t1 and gap["end_s"] > t0:
            after = next((i for i, p in enumerate(plans) if p.sequences[0] > gap["sequence"]), len(plans))
            groups.setdefault(after, []).append(gap)
    for after, gaps in sorted(groups.items()):
        listed = ", ".join(f"sequence {g['sequence']} ({g['why']})" for g in gaps)
        if 0 < after < len(plans):
            before = next(iter(plans[after - 1].files.values()))[-1]
            seconds = plans[after].start_s - before.end_s
            where = (f"{seconds:g} s from the end of sequence {before.sequence} to the start of sequence "
                     f"{plans[after].sequences[0]}")
            target = plans[after]
        elif after == 0:
            seconds = plans[0].start_s - gaps[0]["start_s"]
            where = f"{seconds:g} s before sequence {plans[0].sequences[0]}, where this run starts"
            target = plans[0]
        else:
            last = next(iter(plans[-1].files.values()))[-1]
            seconds = gaps[-1]["end_s"] - last.end_s
            where = f"{seconds:g} s after sequence {last.sequence}, where this run ends"
            target = plans[-1]
        note = f"phoenix_gap: {listed} left out of every channel, {where}"
        target.notes.append(note)
        logger.warning(f"{name}: {note}")


def plan_runs(files: dict[int, list[PhoenixFile]], rate: float, start=None, end=None) -> list[RunPlan]:
    """Group a recording's continuous files into runs.

    The channel folders are first aligned (`_aligned_files`): a sequence
    that some folder lacks, or holds with another sample count, is left
    out of every channel. A file joins the run when it starts where the
    one before ends, to within half a sample; any other start (a missing
    sequence number, a file cut short) starts a new run, so a sequence
    left out ends one run at the last sequence before it and starts the
    next at the first sequence after it that every folder holds. Its
    seconds are logged and go into a "phoenix_gap" note of the run after
    it (`RunPlan.notes`, `_gap_notes`). A recording whose folders agree
    gives the runs it gave before the alignment (up to 8a72107 such a
    recording was refused). `start` and `end` keep the files that overlap
    the window, by their starts as mt-io dates them.

    Args:
        files (dict): `recording_files` of one continuous type.
        rate (float): The site's sample rate in Hz.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.

    Returns:
        list of RunPlan: The runs, in time order.

    Raises:
        ValueError: If a file's rate is not `rate`, no sequence is held by
            every channel folder, or no file overlaps the window.
    """
    folders = sorted(files)
    _check_rates(files, rate)
    files, dropped = _aligned_files(files)
    reference = files[folders[0]]
    if not reference:
        listed = ", ".join(f"sequence {g['sequence']} ({g['why']})" for g in dropped[:5])
        raise ValueError(f"no sequence is held by every channel folder ({', '.join(str(f) for f in folders)}): "
                         f"{listed}")
    name = reference[0].path.parent.parent.name
    t0 = pd.Timestamp(start, tz="UTC").timestamp() if start else -np.inf
    t1 = pd.Timestamp(end, tz="UTC").timestamp() if end else np.inf
    keep = [k for k, f in enumerate(reference) if f.start_s < t1 and f.end_s > t0]
    if not keep:
        raise ValueError(f"no {reference[0].path.suffix} file of {reference[0].path.parent.parent} overlaps "
                         f"[{start}, {end})")
    runs: list[list[int]] = []
    for k in keep:
        if runs and runs[-1][-1] == k - 1 and abs(reference[k].start_s - reference[k - 1].end_s) <= _JOIN_TOLERANCE_SAMPLES / rate:
            runs[-1].append(k)
        else:
            runs.append([k])
    if len(runs) > 1:
        logger.info(f"{name}: {len(runs)} runs; a file does not start where the one before ends at sequence(s) "
                    f"{[reference[r[0]].sequence for r in runs[1:]]}")
    plans = [RunPlan(files={folder: [files[folder][k] for k in run] for folder in folders}) for run in runs]
    _gap_notes(plans, dropped, t0, t1, name)
    return plans


def stamp_correction(reader_start_s: float, expected_s: float, version: int, name: str) -> float:
    """Return the seconds to add to a time stamp mt-io read from a Phoenix file.

    Files of version below `STAMP_CORRECTED_BELOW` stamp their samples
    `STAMP_CORRECTION_S` behind GPS. mt-io's start is compared with its
    own arithmetic (`mt_workbench.instruments.phoenix_file_start`, from
    the header): equal, the correction is due; already later by the
    correction (a reader that corrects it), the correction is 0. The caller
    dates the samples from mt-io's start plus the value returned, so the
    first sample lands on GPS time either way.

    Args:
        reader_start_s (float): The start mt-io gave, UTC seconds.
        expected_s (float): mt-io's arithmetic without the correction.
        version (int): The file's format version.
        name (str): The file, for the message.

    Returns:
        float: `STAMP_CORRECTION_S` or 0.0.

    Raises:
        ValueError: If mt-io's start is neither, for this version.
    """
    diff = reader_start_s - expected_s
    if version >= STAMP_CORRECTED_BELOW:
        if abs(diff) <= _STAMP_TOLERANCE_S:
            return 0.0
    elif abs(diff) <= _STAMP_TOLERANCE_S:
        return STAMP_CORRECTION_S
    elif abs(diff - STAMP_CORRECTION_S) <= _STAMP_TOLERANCE_S:
        return 0.0
    raise ValueError(f"{name}: mt-io dates it {diff:+.6f} s from the header arithmetic (recording id - leap "
                     f"seconds + 1 s or + fragment x (sequence - 1)) at file version {version}: the reader's "
                     f"time rule has changed; check it before correcting the version-2 second")


def stamp_note(correction: float, version: int) -> str:
    """Return the comment line recording the stamp correction of a run."""
    if correction:
        return (f"{_STAMP_PREFIX}{correction!r} s added to every time stamp (file version {version} stamps are "
                f"{STAMP_CORRECTION_S:g} s behind GPS, Phoenix DAA09)")
    return f"{_STAMP_PREFIX}0.0 s added (file version {version}, or the reader already corrects it)"


def station_record(station_md, site_name: str):
    """Clear what mt-io's station metadata says of its own run and channels, and name the station.

    mt-io's reader fills the station's run list, run entries and recorded
    channels with its own run id (``sr150_0001``, ``sr24000_0001``) and
    channel tag (``e1``). Kept, the archive's station lists a run that does
    not exist and a channel named e1, and aurora's export of the transfer
    function stops on the e1 ("Component 'e1' not found in
    channel_nomenclature_dict"). mth5 fills the lists again as the runs are
    written.

    Args:
        station_md: mt_metadata Station, modified in place.
        site_name (str): The station's id.

    Returns:
        The same Station.
    """
    station_md.id = site_name
    # emptied in place first: mt_metadata's Station validator adds back a run for every id left in
    # run_list when the runs are set, and a channel for every name left in channels_recorded
    station_md.run_list.clear()
    station_md.channels_recorded.clear()
    station_md.runs = []
    return station_md


def run_record(run_md):
    """Clear the channels mt-io's run metadata lists under its own tags (see `station_record`).

    Args:
        run_md: mt_metadata Run, modified in place; the RunTS built with it
            lists the channels it is given.

    Returns:
        The same Run.
    """
    for name in ("channels_recorded_electric", "channels_recorded_magnetic", "channels_recorded_auxiliary"):
        getattr(run_md, name).clear()
    run_md.channels = []
    return run_md


def _seconds(value) -> float:
    """Return an mt-io time (MTime or text) as UTC seconds since the epoch."""
    return pd.Timestamp(str(getattr(value, "isoformat", lambda: value)())).timestamp()


def coil_self_reports(rec: PhoenixRecording) -> dict[int, list[str]]:
    """Return the coil serials the coils reported in the recording's backend.log.

    A coil reports itself when the receiver starts, in lines such as
    "Channel Module Sensor Message (Ch3):SMS I 17 00 MTC150L - SE53508A",
    where 3 is the channel folder index.

    Args:
        rec (PhoenixRecording): The recording.

    Returns:
        dict: Channel folder index to the serials reported, in order of
        first report; {} when there is no backend.log.
    """
    log = rec.path / "backend.log"
    out: dict[int, list[str]] = {}
    if not log.is_file():
        return out
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        hit = _SELF_REPORT.search(line)
        if hit:
            serials = out.setdefault(int(hit.group(1)), [])
            if hit.group(2) not in serials:
                serials.append(hit.group(2))
    return out


def _metadata_serial(rec: PhoenixRecording, tag: str, md) -> str:
    """Return the coil serial mt-io read for a channel (from the metadata file it takes)."""
    return str(md.sensor.id or "")


def _metadata_dipole(rec: PhoenixRecording, tag: str, md) -> float:
    """Return the dipole length mt-io read for a channel (length1 + length2 of the metadata file it takes)."""
    return float(md.dipole_length or 0.0)


def _units_stage(chain: list, name: str):
    """Return the stage that takes mt-io's `v_to_mv` place, and whether it replaced it.

    Args:
        chain (list): mt-io's filters for one channel.
        name (str): The channel, for the message.

    Returns:
        tuple: (filter, replaced). A `v_to_mv` stage of gain
        `MTIO_V_TO_MV_GAIN` is replaced by `MV_TO_V`; one of gain 1/1000
        (a reader that already fixed it) is kept.

    Raises:
        ValueError: If the chain holds no such stage.
    """
    from mt_metadata.timeseries.filters import CoefficientFilter

    found = [f for f in chain if f.name == MTIO_V_TO_MV]
    if len(found) == 1 and abs(float(found[0].gain) - MTIO_V_TO_MV_GAIN) < 1e-9:
        stage = CoefficientFilter()
        stage.name, stage.gain = MV_TO_V, 1.0 / MTIO_V_TO_MV_GAIN
        stage.units_in, stage.units_out = "milliVolt", "Volt"
        stage.comments = "Phoenix receiver output: the coil or dipole millivolts as recorded volts"
        return stage, True
    if len(found) == 1 and abs(float(found[0].gain) * MTIO_V_TO_MV_GAIN - 1.0) < 1e-9:
        return found[0], False
    raise ValueError(f"{name}: mt-io's chain {[(f.name, getattr(f, 'gain', None)) for f in chain]} has no "
                     f"{MTIO_V_TO_MV} stage of gain {MTIO_V_TO_MV_GAIN:g} (or 1/{MTIO_V_TO_MV_GAIN:g}); "
                     f"the reader's units have changed, check them before ingesting")


def _dipole_stage(length_m: float):
    """Return the dipole stage of an electric channel: mV/km in, mV out, gain L / 1000."""
    from mt_metadata.timeseries.filters import CoefficientFilter

    stage = CoefficientFilter()
    stage.name, stage.gain = f"dipole_{length_m:g}m", float(length_m) / 1000.0
    stage.units_in, stage.units_out = "milliVolt per kilometer", "milliVolt"
    return stage


def calibration_epoch(path: Path) -> int:
    """Return the calibration time of a ``<serial>_<epoch hex>.<scal|rxcal>.json``, UTC seconds.

    The hex of the name is taken; a name without it gives the file's
    `timestamp_utc`.

    Raises:
        ValueError: If neither gives a time.
    """
    hit = re.match(r"^\d+_([0-9A-Fa-f]{8})\.", Path(path).name)
    if hit:
        return int(hit.group(1), 16)
    stamp = json.loads(Path(path).read_text(encoding="utf-8")).get("timestamp_utc")
    if stamp is None:
        raise ValueError(f"{Path(path).name}: no epoch in the name and no timestamp_utc inside")
    return int(stamp)


def calibration_date(path: Path) -> str:
    """Return the UTC date of a calibration file's epoch (`calibration_epoch`), YYYY-MM-DD."""
    return pd.Timestamp(calibration_epoch(path), unit="s", tz="UTC").strftime("%Y-%m-%d")


# the lowest measured record of each low-pass band of a binary .rxcal, Hz (scripts/phoenix_cal_convert.py)
RXCAL_LOWEST_RECORD_HZ = {10000: 1024.0, 1000: 110.0, 100: 15.0, 10: 0.2}


def _rxcal_dates(rxcal: Path, lp=None) -> str:
    """Return the date part of a channel comment's rxcal piece.

    "calibrated <date>" for an EMpower file. For a file converted from
    the binary form (`curve_below_records_from` in it), whose curve below
    each band's lowest record was copied from another file, "records
    calibrated <date>; curve below <f> Hz from <file>", the frequency that
    of the band of low-pass `lp` (`RXCAL_LOWEST_RECORD_HZ`; left out for
    another low-pass).

    Args:
        rxcal (Path): The receiver calibration file.
        lp (int or str, optional): The channel's low-pass setting, Hz.
    """
    date = calibration_date(rxcal)
    source = json.loads(Path(rxcal).read_text(encoding="utf-8")).get("curve_below_records_from")
    if not source:
        return f"calibrated {date}"
    try:
        lowest = RXCAL_LOWEST_RECORD_HZ.get(int(float(lp)))
    except (TypeError, ValueError):
        lowest = None
    below = f"curve below {lowest:g} Hz" if lowest is not None else "curve below the records"
    return f"records calibrated {date}; {below} from {source}"


def calibration_for(found: list, start_s: float | None, what: str) -> Path:
    """Choose a calibration file for a recording that starts at `start_s`.

    The latest file whose epoch (`calibration_epoch`) is at or before the
    start, else the earliest after it. A single file is taken whatever its
    date, as before the rule. A file dated after the start is taken with
    one warning naming the unit, the file and the days between.

    Args:
        found (list of Path): The candidate files, at least one.
        start_s (float or None): The recording's start, UTC seconds.
        what (str): The coil or receiver, for the message.

    Returns:
        Path: The file chosen.

    Raises:
        ValueError: If there are several files and no start, or two files
            of the same epoch.
    """
    if len(found) == 1:
        chosen = Path(found[0])
        try:
            epoch = calibration_epoch(chosen) if start_s is not None else None
        except (ValueError, OSError):
            epoch = None
        if epoch is not None and epoch > start_s:
            _warn_after_start(what, chosen, epoch, start_s)
        return chosen
    names = ", ".join(Path(f).name for f in found)
    if start_s is None:
        raise ValueError(f"{what}: {len(found)} calibration files ({names}) and no recording start to choose by")
    dated = sorted((calibration_epoch(f), Path(f)) for f in found)
    epochs = [e for e, _ in dated]
    if len(set(epochs)) != len(epochs):
        raise ValueError(f"{what}: two calibration files of one epoch among {names}")
    before = [f for e, f in dated if e <= start_s]
    if before:
        return before[-1]
    epoch, chosen = dated[0]
    _warn_after_start(what, chosen, epoch, start_s)
    return chosen


def _warn_after_start(what: str, chosen: Path, epoch: int, start_s: float) -> None:
    """Log one warning line: the calibration file taken is dated after the recording's start."""
    logger.warning(f"{what}: {chosen.name} taken, dated {(epoch - start_s) / 86400:.1f} days after the recording's "
                   f"start (no file at or before it)")


def _coil_stage(serial: str, calibration_dir: Path, start_s: float | None = None):
    """Return a coil's response stage from its ``<serial>_*.scal.json``, or None when there is none.

    The table (mV per nT against frequency) is mt-io's
    `PhoenixCalibration`, renamed ``phoenix_coil_<serial>`` and labelled nT
    in, mV out. Of several files, the one `calibration_for` dates to the
    recording is taken.

    Args:
        serial (str): The coil serial.
        calibration_dir (Path): The folder of scal files.
        start_s (float or None): The recording's start, UTC seconds; needed
            only when the coil has several files.

    Returns:
        tuple: (filter or None, the scal file or None, the receiver it was
        calibrated on or None).

    Raises:
        ValueError: If `calibration_for` refuses, or the file holds no coil
            table.
    """
    from mt_io.phoenix.readers.calibrations import PhoenixCalibration

    found = sorted(Path(calibration_dir).glob(f"{serial}_*.scal.json"))
    if not found:
        return None, None, None
    chosen = calibration_for(found, start_s, f"coil {serial} in {calibration_dir}")
    cal = PhoenixCalibration(chosen)
    tables = [v for k, v in vars(cal).items() if k.startswith("h") and hasattr(v, "frequencies")]
    if len(tables) != 1:
        raise ValueError(f"{chosen.name}: {len(tables)} coil tables, expected 1")
    stage = tables[0]
    stage.name = f"{COIL_PREFIX}{serial}"
    stage.units_in, stage.units_out = "nanoTesla", "milliVolt"
    calibrated_on = json.loads(chosen.read_text(encoding="utf-8")).get("inst_serial")
    return stage, chosen, calibrated_on


def _h_polarity_stage():
    """Return the polarity stage of a magnetic channel: mV in, mV out, gain `H_POLARITY_GAIN` (-1).

    The Phoenix records H with the sign of the LEMI-423's recorded H;
    mt-workbench's convention (lemimt's, the LEMI-423 chain's
    `lemi423_b_scale` of gain -1000) negates H, and this stage puts the
    Phoenix H into it. Measured at Kalkaroo 2021: the stored Phoenix volts
    and the stored LEMI-423 counts of KD-RR_210428 and KD-RRa_210428 (13 m
    apart) are in phase in 12 of 12 hours; the 586 rxcal and scal tables
    are within 8.6 deg of 0 at 1 Hz; and the LEMI-423's recorded H has the
    observatories' sign (upstream issue 68). So the Phoenix H that mt-io
    gives, calibrated through a positive coil table, is geographic, and
    the -1 is mt-workbench's own: calibrated H is minus geographic in this
    convention, for the LEMI-423 and, with this stage, the Phoenix. Without
    the stage, the 11 S1 sites equal AusMT's impedances within 0.7 deg and
    0.01 dex once 180 deg is added, and on mt-workbench's single-site check
    7 of 8 S3 and 5 of 5 S2 Phoenix sites sit in the opposite quadrants,
    where AusMT's are standard at 9 of 9 and 5 of 5 (upstream issue 81).
    If the LEMI-423's -1 moves from H to E (issue 68), this stage moves to
    the Phoenix E with it. The stage sits at the receiver's input, after
    the coil (or first, when the coil table is missing), so the units
    chain stays consistent either way. Like `lemi423_b_scale` on hz, it
    leaves the tipper unchanged; no Kalkaroo Phoenix recording has an hz,
    so on hz it rests on the H1-H3 inputs being the same.

    Returns:
        CoefficientFilter: The stage, named `H_POLARITY`.
    """
    from mt_metadata.timeseries.filters import CoefficientFilter

    stage = CoefficientFilter()
    stage.name, stage.gain = H_POLARITY, H_POLARITY_GAIN
    stage.units_in, stage.units_out = "milliVolt", "milliVolt"
    stage.comments = H_POLARITY_COMMENT
    return stage


def _channel_chain(reader, rec: PhoenixRecording, folder: int, site, calibration_dir, md) -> tuple[list, list[str], bool]:
    """Return a channel's filter chain from the field to the recorded volts and its comment pieces.

    mt-io's chain for the channel (the receiver's curve from the rxcal
    file, `v_to_mv` and, for E, the dipole) is taken apart: the receiver
    curve is kept, `v_to_mv` is replaced (`_units_stage`), the dipole is
    rebuilt at the length used, and on hx, hy and hz the coil table
    (`_coil_stage`) and the polarity stage (`_h_polarity_stage`, gain -1,
    the comment piece "phoenix_h_polarity -1") are added; E gets no
    polarity stage. At a site declared `swap_e` the channel is the one
    `component_of` stores the input as: an electric input takes the
    declared dipole length and azimuth of that channel (the line its
    samples hold), the metadata file's length of its own input, and the
    comment piece "swap_e: the E2 input stored as ex, ..."
    (`swap_e_piece`). The receiver and coil files are the ones
    `calibration_for` dates to the recording's start (`rec.start_s`), and
    the comment names each with its date (`_rxcal_dates`). The channel
    metadata's coil serial and dipole length are set to the ones used.

    Args:
        reader: mt-io's reader of the channel's first file.
        rec (PhoenixRecording): The recording.
        folder (int): The channel folder index.
        site (SiteConfig): The site's settings.
        calibration_dir (Path): The folder of rxcal and scal files.
        md: The channel metadata, modified in place.

    Returns:
        tuple: (filters from the field to the volts, comment pieces,
        whether `v_to_mv` was replaced).

    Raises:
        ValueError: If there is no calibration folder, the receiver curve
            is not one stage, or `_units_stage`, `_rxcal` or `_coil_stage`
            refuses.
    """
    tag = rec.tags[folder]
    swap_e = bool(getattr(site, "swap_e", False))
    comp = component_of(tag, swap_e)
    if calibration_dir is None:
        raise ValueError(f"{site.name}: a Phoenix site needs calibration_dir (the folder of the receivers' "
                         f"rxcal.json and the coils' scal.json files)")
    start_s = rec.start_s
    rxcal = _rxcal(rec, calibration_dir, start_s)
    filters = list(reader.get_channel_response(rxcal_fn=rxcal).filters_list)
    curves = [f for f in filters if "lowpass" in f.name]
    if len(curves) != 1:
        raise ValueError(f"{site.name} {comp}: {len(curves)} receiver curves in mt-io's chain {[f.name for f in filters]}")
    units, replaced = _units_stage(filters, f"{site.name} {comp}")
    lp = rec.chan(rec.tags[min(rec.tags)]).get("lp")
    pieces, field_stage = [], None
    other = rec.recmeta
    if md.type == "electric":
        declared = float(getattr(site, f"dipole_length_{comp}", 0.0) or 0.0)
        from_meta = _metadata_dipole(rec, tag, md)
        length = declared or from_meta
        if not length:
            raise ValueError(f"{site.name} {comp}: no dipole length in {rec.meta_path.name} and none declared")
        if declared and abs(declared - from_meta) > DIPOLE_DIFF_M:
            logger.info(f"{site.name} {comp}: dipole {declared:g} m from survey.yaml, {rec.meta_path.name} "
                        f"{from_meta:g} m")
        field_stage = _dipole_stage(length)
        md.dipole_length = length
        theirs = rec.chan(tag, other)
        alt = f", recmeta.json {float(theirs.get('length1', 0)) + float(theirs.get('length2', 0)):g}" if theirs else ""
        pieces.append(f"dipole {length:g} m from {'survey.yaml' if declared else rec.meta_path.name}, "
                      f"{rec.meta_path.name} {from_meta:g}{alt}")
        if swap_e:
            # the input's own azimuth (mt-io's, by its tag) is the other line's: the stored channel's is declared
            azimuth = float(getattr(site, f"azimuth_{comp}"))
            md.measurement_azimuth = azimuth
            pieces.append(swap_e_piece(tag, comp, azimuth))
    else:
        declared = getattr(site, f"coil_{comp}", None)
        from_meta = _metadata_serial(rec, tag, md)
        serial = str(declared) if declared else from_meta
        reports = coil_self_reports(rec).get(folder, [])
        theirs = rec.chan(tag, other)
        text = f"coil {serial} from {'survey.yaml' if declared else rec.meta_path.name}"
        if declared:
            text += f", {rec.meta_path.name} {from_meta}"
        if theirs:
            text += f", recmeta.json {theirs.get('serial')}"
        text += f", self-report {' '.join(reports) if reports else 'none in backend.log'}"
        if reports and serial not in reports:
            text += ", coil self-report differs"
            logger.warning(f"{site.name} {comp}: coil {serial} from {'survey.yaml' if declared else rec.meta_path.name}, "
                           f"but the coil on folder {folder} reported {' '.join(reports)} in backend.log")
        pieces.append(text)
        md.sensor.id = serial
        field_stage, scal, calibrated_on = _coil_stage(serial, calibration_dir, start_s)
        if field_stage is None:
            logger.warning(f"{site.name} {comp}: no {serial}_*.scal.json in {calibration_dir}: no coil response "
                           f"(Z and M wrong here, T and rrH unaffected)")
            pieces.append("coil response missing: Z and M wrong here, T and rrH unaffected")
        else:
            pieces.append(f"scal {scal.name} (calibrated {calibration_date(scal)} on receiver {calibrated_on})")
    pol = rec.chan(tag).get("polInv")
    pieces.append(f"polInv {str(bool(pol)).lower() if pol is not None else 'not recorded'}")
    if pol:
        logger.warning(f"{site.name} {comp}: polInv true in {rec.meta_path.name}; recorded, the samples left as "
                       f"recorded")
    pieces.append(f"rxcal {rxcal.name} ({_rxcal_dates(rxcal, lp)}) {lp} Hz curve")
    polarity = _h_polarity_stage() if md.type != "electric" else None
    if polarity is not None:
        pieces.append(f"{polarity.name} {polarity.gain:g}")
    chain = [f for f in (field_stage, polarity, units, curves[0]) if f is not None]
    return chain, pieces, replaced


def _rxcal(rec: PhoenixRecording, calibration_dir, start_s: float | None = None) -> Path:
    """Return the receiver's calibration file ``<receiver>_*.rxcal.json`` in `calibration_dir`.

    Of several files, the one `calibration_for` dates to a recording that
    starts at `start_s` (UTC seconds) is taken.

    Raises:
        FileNotFoundError: If there is none.
        ValueError: If `calibration_for` refuses.
    """
    found = sorted(Path(calibration_dir).glob(f"{rec.receiver}_*.rxcal.json"))
    if not found:
        raise FileNotFoundError(f"no {rec.receiver}_*.rxcal.json (receiver {rec.receiver}) in {calibration_dir}")
    return calibration_for(found, start_s, f"receiver {rec.receiver} in {calibration_dir}")


def read_continuous(rec: PhoenixRecording, plan: RunPlan, site, calibration_dir=None):
    """Read one run of a recording's continuous files into a RunTS.

    Each file is read with mt-io's `open_phoenix(fn).read()`; the samples
    must number (size - 128) / 4. The channel metadata is mt-io's for the
    run's first file, renamed (`component_of`), with the run's start, which is
    mt-io's plus `stamp_correction`, and the chain of `_channel_chain`.
    Every file's start is checked the same way and must give the same
    correction.

    Args:
        rec (PhoenixRecording): The recording.
        plan (RunPlan): The run's files (`plan_runs`).
        site (SiteConfig): The site's settings.
        calibration_dir (Path): The folder of rxcal and scal files
            (`_channel_chain`).

    Returns:
        tuple: (RunTS, run comment pieces ending with the plan's gap notes,
        `RunPlan.notes`, the stamp correction in s).

    Raises:
        ValueError: If a file reads another number of samples than its
            size gives, its start fails `stamp_correction`, or the
            corrections differ between files.
    """
    from mt_io.phoenix.read import open_phoenix
    from mt_timeseries import ChannelTS, RunTS

    channels, corrections, replacements = [], set(), set()
    shifts = set()
    run_md = station_md = None
    versions = set()
    for folder, files in plan.files.items():
        parts, first = [], None
        for pf in files:
            reader = open_phoenix(pf.path)
            try:
                reader_s = _seconds(reader.segment_start_time)
                correction = stamp_correction(reader_s, pf.start_s, pf.version, pf.path.name)
                corrections.add(correction)
                # mt-io's start plus the correction, as the shift from the header arithmetic
                shifts.add(round(reader_s - pf.start_s, 6) + correction)
                versions.add(pf.version)
                data = reader.read()
                if data.size != pf.n:
                    raise ValueError(f"{pf.path.name}: mt-io read {data.size} samples, the file holds {pf.n}")
                parts.append(data)
                if first is None:
                    first = reader
                    md = reader.channel_metadata.copy()
                    chain, pieces, replaced = _channel_chain(reader, rec, folder, site, calibration_dir, md)
                    replacements.add(replaced)
                    if run_md is None:
                        run_md, station_md = reader.run_metadata.copy(), reader.station_metadata.copy()
            finally:
                reader.close()
        if len(corrections) != 1 or len(shifts) != 1:
            raise ValueError(f"{rec.path}: the files of one run need different stamp corrections {corrections} "
                             f"(shifts from the header arithmetic {shifts})")
        tag = rec.tags[folder]
        md.component = component_of(tag, bool(getattr(site, "swap_e", False)))
        md.channel_number = folder
        md.filters = []
        for stage, f in enumerate(chain, 1):
            md.add_filter(name=f.name, applied=True, stage=stage)
        start = pd.Timestamp(plan.start_s + next(iter(shifts)), unit="s", tz="UTC")
        md.time_period.start = start.isoformat()
        md.time_period.end = (start + pd.Timedelta(seconds=(plan.n - 1) / files[0].rate)).isoformat()
        md.sample_rate = files[0].rate
        pieces = [f"phoenix: folder {folder}, tag {tag.upper()}", *pieces]
        channels.append((md, np.concatenate(parts), chain, pieces))
    from mt_metadata.timeseries.filters import ChannelResponse

    correction = next(iter(corrections))
    version = min(versions)
    note = stamp_note(correction, version)
    station_record(station_md, site.name)
    run_record(run_md)
    first_md = channels[0][0]
    t_start = pd.Timestamp(_seconds(first_md.time_period.start), unit="s", tz="UTC")
    t_end = t_start + pd.Timedelta(seconds=(plan.n - 1) / first_md.sample_rate)
    for period in (run_md.time_period, station_md.time_period):
        period.start, period.end = t_start.isoformat(), t_end.isoformat()
    built = []
    for md, data, chain, pieces in channels:
        md.comments = ", ".join(pieces) + "; " + note
        built.append(ChannelTS(channel_type=md.type, data=data, channel_metadata=md,
                               channel_response=ChannelResponse(filters_list=chain)))
    run = RunTS(array_list=built, run_metadata=run_md, station_metadata=station_md)
    for md, _data, chain, _pieces in channels:
        for f in chain:
            run.filters[f.name] = f
    provenance = run.station_metadata.provenance
    if note not in str(provenance.comments.value or ""):
        prior = str(provenance.comments.value or "")
        provenance.comments.value = f"{prior}; {note}" if prior else note
    seqs = plan.sequences
    other = " (recmeta.json also present)" if rec.recmeta is not None else ""
    pieces = [f"phoenix: {rec.model} ({rec.receiver_model}) receiver {rec.receiver}, recording {rec.recording_id}, "
              f"files {seqs[0]}-{seqs[-1]}, folders {' '.join(str(f) for f in plan.files)}, file version {version}, "
              f"metadata {rec.meta_path.name}{other}", note]
    if True in replacements:
        pieces.append(UNITS_NOTE)
    pieces += plan.notes
    return run, pieces, correction


@dataclass
class Burst:
    """One burst of a `.td_24k` file, from the file's sub-headers.

    Attributes:
        path (Path): The file.
        index (int): The burst's place in the file, from 0.
        stamp (int): Its GPS stamp, seconds.
        n (int): Its samples.
        start_s (float): UTC time of its first sample as mt-io dates it,
            without `STAMP_CORRECTION_S`.
    """

    path: Path
    index: int
    stamp: int
    n: int
    start_s: float


def burst_index(path: Path) -> list[Burst]:
    """Walk a `.td_24k` file's sub-headers without reading the samples.

    After the 128-byte header each burst is a 32-byte sub-header, whose
    first two little-endian unsigned ints are the GPS stamp and the sample
    count, then that many float32 samples. A burst cut short at the end of
    the file is left out with a warning.

    Args:
        path (Path): A `.td_24k` file.

    Returns:
        list of Burst: The file's bursts in order.
    """
    import struct

    from .instruments import PHOENIX_SUBHEADER_BYTES, gps_to_utc_seconds

    path = Path(path)
    size = path.stat().st_size
    out, offset = [], PHOENIX_HEADER_BYTES
    with open(path, "rb") as f:
        while offset + PHOENIX_SUBHEADER_BYTES <= size:
            f.seek(offset)
            stamp, n = struct.unpack("<II", f.read(8))
            end = offset + PHOENIX_SUBHEADER_BYTES + 4 * n
            if end > size:
                logger.warning(f"{path.name}: burst {len(out)} cut short ({(size - offset - PHOENIX_SUBHEADER_BYTES) // 4} "
                               f"of {n} samples): left out")
                break
            out.append(Burst(path=path, index=len(out), stamp=int(stamp), n=int(n),
                             start_s=float(gps_to_utc_seconds(stamp))))
            offset = end
    return out


def cut_burst_samples(path: Path, walk: list[Burst]) -> int | None:
    """Return the samples a `.td_24k` file holds of the burst cut short at its end.

    mt-io's `DecimatedSegmentCollection` returns such a burst with the
    samples the file holds; `burst_index` leaves it out. The ingest drops
    mt-io's trailing burst when its size is this count (upstream issue 73).

    Args:
        path (Path): A `.td_24k` file.
        walk (list of Burst): `burst_index` of the file.

    Returns:
        int or None: The samples after the cut burst's sub-header; None
        when the file ends on a whole burst.
    """
    from .instruments import PHOENIX_SUBHEADER_BYTES

    end = PHOENIX_HEADER_BYTES + sum(PHOENIX_SUBHEADER_BYTES + 4 * b.n for b in walk)
    held = Path(path).stat().st_size - end - PHOENIX_SUBHEADER_BYTES
    return held // 4 if held >= 0 else None


def _read_bursts(path: Path) -> list[tuple[float, np.ndarray]]:
    """Read every burst of a `.td_24k` file through mt-io.

    The installed mt-io's `read_phoenix` and `DecimatedSegmentedReader`
    return the first burst only; its `DecimatedSegmentCollection` reads
    them all, once, on a fresh reader (a second read of the same reader
    returns none). The fork's `testing` branch makes `read_phoenix` return
    them all; with it installed this is the one call to change.

    Args:
        path (Path): A `.td_24k` file.

    Returns:
        list of tuple: (UTC start in seconds as mt-io dates it, float32
        samples) per burst.
    """
    from mt_io.phoenix.readers.segmented.decimated_segmented_reader import DecimatedSegmentCollection

    reader = DecimatedSegmentCollection(path)
    try:
        segments = reader.read_segments()
    finally:
        reader.close()
    return [(_seconds(seg.gps_time_stamp), seg.data) for seg in segments]


@dataclass
class BurstSlot:
    """The bursts of every channel folder that share one stamp."""

    stamp: int
    start_s: float
    n: int
    bursts: dict  # folder index -> Burst


def burst_slots(rec: PhoenixRecording, start=None, end=None) -> tuple[list[BurstSlot], list[int]]:
    """Match a recording's bursts across its channel folders by stamp.

    Args:
        rec (PhoenixRecording): The recording.
        start: Window start, UTC; None for no bound.
        end: Window end, UTC; None for no bound.

    Returns:
        tuple: (the slots every channel folder holds with the same sample
        count, in time order; the stamps of the window some folder lacks or
        whose counts differ).

    Raises:
        ValueError: If the recording holds no burst file.
    """
    from .instruments import PHOENIX_BURSTS

    files = recording_files(rec, PHOENIX_BURSTS)
    if not files:
        raise ValueError(f"{rec.path}: no {PHOENIX_BURSTS} files")
    t0 = pd.Timestamp(start, tz="UTC").timestamp() if start else -np.inf
    t1 = pd.Timestamp(end, tz="UTC").timestamp() if end else np.inf
    by_folder: dict[int, dict[int, Burst]] = {}
    for folder, fs in files.items():
        mine = by_folder.setdefault(folder, {})
        for pf in fs:
            if pf.start_s >= t1:
                continue
            for b in burst_index(pf.path):
                if t0 <= b.start_s < t1:
                    mine[b.stamp] = b
    every = set().union(*(set(v) for v in by_folder.values()))
    slots, missing = [], []
    for stamp in sorted(every):
        held = {f: v[stamp] for f, v in by_folder.items() if stamp in v}
        counts = {b.n for b in held.values()}
        if len(held) != len(by_folder) or len(counts) != 1:
            missing.append(stamp)
            continue
        first = next(iter(held.values()))
        slots.append(BurstSlot(stamp=stamp, start_s=first.start_s, n=first.n, bursts=held))
    return slots, missing


def run_h_polarity(filters: dict) -> bool | None:
    """Tell whether a run's Phoenix magnetic channels carry the polarity stage, from their filter lists.

    A Phoenix magnetic channel is an hx, hy or hz whose chain holds
    `MV_TO_V`, which only the Phoenix ingest writes.

    Args:
        filters (dict): {channel: [filter names]} of one run, in the order
            of the chain (`_filter_names` reads them from an archive).

    Returns:
        bool or None: True when every Phoenix magnetic channel holds
        `H_POLARITY`, False when one lacks it (an archive built before the stage),
        None when the run has no Phoenix magnetic channel.
    """
    held = [H_POLARITY in names for comp, names in filters.items()
            if str(comp).lower() in ("hx", "hy", "hz") and MV_TO_V in names]
    if not held:
        return None
    return all(held)


def _filter_names(dataset) -> list[str]:
    """Return the filter names of an archive channel's chain, from its h5py attributes.

    mth5 file version 0.2.0 keeps them as the JSON list ``filters`` of
    ``{"applied_filter": {"name": ...}}`` entries, version 0.1.0 as
    ``filter.name``.
    """
    raw = dataset.attrs.get("filters")
    if raw is not None:
        text = raw.decode() if isinstance(raw, bytes) else str(raw)
        try:
            items = json.loads(text)
        except ValueError:
            return []
        names = []
        for item in items if isinstance(items, list) else []:
            entry = item.get("applied_filter", item) if isinstance(item, dict) else {}
            if isinstance(entry, dict) and entry.get("name"):
                names.append(str(entry["name"]))
        return names
    raw = dataset.attrs.get("filter.name")
    if raw is None:
        return []
    return [n.decode() if isinstance(n, bytes) else str(n) for n in np.atleast_1d(raw)]


def archive_h_polarity(path: Path, site_name: str) -> bool | None:
    """Tell whether a site's archive holds its Phoenix H with the polarity stage.

    Every run of the station is read with h5py (read-only, no file lock),
    through its channels' filter lists (`run_h_polarity`); the first run
    whose Phoenix magnetic channels lack the stage ends the read.

    Args:
        path (Path): The archive (raw, filtered variant or burst archive).
        site_name (str): The station in it, under the archive's first survey.

    Returns:
        bool or None: True when every run with Phoenix magnetic channels
        holds the stage, False when one lacks it, None when the archive or
        the station is missing or holds no Phoenix magnetic channel (a LEMI,
        EDL or derived archive).
    """
    import h5py

    path = Path(path)
    if not path.is_file():
        return None
    seen = None
    with h5py.File(path, "r", locking=False) as archive:
        surveys = archive.get("Experiment/Surveys")
        if surveys is None or not len(surveys):
            return None
        station = surveys[list(surveys)[0]].get(f"Stations/{site_name}")
        if station is None:
            return None
        for run in station.values():
            if not isinstance(run, h5py.Group):
                continue
            filters = {name: _filter_names(item) for name, item in run.items() if isinstance(item, h5py.Dataset)}
            held = run_h_polarity(filters)
            if held is False:
                return False
            if held:
                seen = True
    return seen


def warn_without_h_polarity(path: Path, site_name: str) -> bool:
    """Log one warning when a site's archive holds Phoenix H built before the polarity stage.

    Until every Phoenix archive is re-ingested, such an archive mixed with
    a re-ingested one or a LEMI-423 site gives a silent -1 (upstream issue
    81). The warning changes nothing in the processing.

    Args:
        path (Path): The archive opened for the site.
        site_name (str): The site.

    Returns:
        bool: True when the warning was logged.
    """
    try:
        held = archive_h_polarity(path, site_name)
    except (OSError, KeyError, ValueError) as exc:
        logger.debug(f"{site_name}: the H polarity of {Path(path).name} not read: {exc}")
        return False
    if held is not False:
        return False
    logger.warning(f"{site_name}: {Path(path).name} was built before the Phoenix H polarity stage ({H_POLARITY} "
                   f"missing on its magnetic channels; docs/upstream_issues.md 81): its Z sits 180 deg off, and M "
                   f"or any product taking its H as an input (not as the remote reference) carries -1 against a "
                   f"re-ingested Phoenix archive or a LEMI-423 site; re-ingest it (scripts/ingest_site.py --force)")
    return True


def archive_stamp_correction(path: Path, site_name: str) -> float | None:
    """Return the stamp correction a Phoenix archive's ingest added, from the station's comments.

    The station group's ``provenance.comments`` attribute is read with
    h5py, read-only and without an HDF5 file lock, as
    `mt_workbench.dclevel.recorded_levels` reads run comments: mth5's
    station metadata builds every run's metadata, 106-206 s for a burst
    archive of 1629 runs (upstream issue 74).

    Args:
        path (Path): The archive.
        site_name (str): The station in it, under the archive's first survey.

    Returns:
        float or None: The correction in seconds; None for an archive that
        records none (not a Phoenix archive).

    Raises:
        MTH5Error: If the archive does not exist or its first survey holds
            no such station, as mth5's open and `get_station` raise.
    """
    import h5py

    from .dclevel import _text

    path = Path(path)
    if not path.is_file():
        from mth5.utils.exceptions import MTH5Error  # imported to raise only: importing mth5 takes about 2 s

        raise MTH5Error(f"Cannot open new file in mode r: {path} does not exist")
    with h5py.File(path, "r", locking=False) as archive:
        surveys = archive["Experiment/Surveys"]
        survey_name = list(surveys)[0]
        station = surveys[survey_name].get(f"Stations/{site_name}")
        if station is None:
            from mth5.utils.exceptions import MTH5Error

            raise MTH5Error(f"Could not find station {site_name}")
        comment = _text(station.attrs.get("provenance.comments"))
    for line in comment.split("; "):
        if line.startswith(_STAMP_PREFIX):
            return float(line[len(_STAMP_PREFIX):].split(" ", 1)[0])
    return None
