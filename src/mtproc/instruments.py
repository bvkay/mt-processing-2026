# -*- coding: utf-8 -*-
"""
Recorders mtproc reads and their detection from a folder of raw files

A site's instrument is determined by its files. The survey names a default
(`instrument:` at the top of survey.yaml), and a site whose folder holds
another recorder's files is detected as that recorder here and written by
`scripts/new_survey.py` as the site's own `instrument:`.

    lemi423  LEMI-423 broadband logger: `<unix epoch>.B423` binary files
             (90 min each), mt_io.lemi.lemi423 -> hx hy hz ex ey (counts; the
             LEMI-120 coil response and `h_scale` are added in mtproc.ingest)
    lemi424  LEMI-424 long-period logger: `YYYYMMDDhhmm.txt`, one text line a
             second (24 fields, or 16 without GPS), mt_io.lemi.lemi424 ->
             bx by bz e1 e2 e3 e4 (+ temperature_e, temperature_h). No filter
             chain: magnetics in nT (fluxgate), electrics as recorded, in mV,
             although the reader labels them mV/km (no dipole length applied)
    edl      Earth Data PR6-24 with the University of Adelaide interface: one
             ASCII (or miniSEED) file per channel, `{station}YYMMDDhhmmss.{BX,
             BY,BZ,EX,EY}`, in day folders, and `config/recorder.ini`;
             mt_io.uoa.pr624 -> hx hy hz ex ey in recorded microVolt with its
             own chain (Bartington 142.857 uV/nT, the 0.4 Bz divider, the
             signed dipole length, the x10 terminal box). A site may declare
             an extra `electric_gain:` for its electric chain beyond that:
             hardwired at the field terminal junction box, and for a survey
             whose PR6-24 configs were not kept, known from the field
             notes. That gain is added as one more filter on ex and ey
             (`ELECTRIC_GAIN_FILTER`)

The mt-io readers are imported inside the functions that use them, so
importing this module (and `mtproc.survey`, which imports it) does not load
mt-io. File names carry each file's start in UTC (`file_start`), which is
what run splitting and `span` use.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

INSTRUMENTS: dict[str, dict] = {
    "lemi423": {"label": "LEMI-423", "pattern": "*.B423", "reader": "mt_io.lemi.lemi423",
                "channels": ("hx", "hy", "hz", "ex", "ey"), "file_seconds": 5400},
    "lemi424": {"label": "LEMI-424", "pattern": "*.txt", "reader": "mt_io.lemi.lemi424",
                "channels": ("bx", "by", "bz", "e1", "e2", "e3", "e4"), "file_seconds": 86400},
    "edl": {"label": "Earth Data PR6-24", "pattern": "*.[BE][XYZ]", "reader": "mt_io.uoa.pr624",
            "channels": ("hx", "hy", "hz", "ex", "ey"), "file_seconds": 3600},
}
LEMI424_ELECTRICS = ("e1", "e2", "e3", "e4")  # every electric column; `channels:` then keeps the wired ones
LEMI424_FIELDS = (24, 16)  # the reader's two line layouts: with and without the GPS block
EDL_FILES = {".BX": "hx", ".BY": "hy", ".BZ": "hz", ".EX": "ex", ".EY": "ey"}  # pr624's mapping
EDL_STAMP = re.compile(r"(\d{12})$")  # YYMMDDhhmmss at the end of the stem
# EDL magnetic sensors (`sensor_type:`, in mt_io.uoa.pr624's names) mapped to the prefix of
# the response filter the reader puts on hx, hy and hz for them
EDL_SENSORS = {"bartington": "uoa_bartington", "lemi120": "lemi_120"}
_EDL_SUFFIXES = {s.lower() for s in EDL_FILES}
# An EDL site's electric chain may carry extra gain between the dipoles and the recorded values,
# beyond what the reader models (the x10 terminal box). It is hardwired at the field terminal
# junction box and, for a survey whose PR6-24 configs were not kept, known
# from the field notes. `SiteConfig.electric_gain` (default 1.0, no filter) declares it, and
# `read_run` adds it as this filter on ex and ey. The filter is forward, like the reader's own gains
# (input microVolt to stored words), so calibration divides by it and the channels come out that
# many times smaller. The archive keeps the words as stored.
ELECTRIC_GAIN_FILTER = "uoa_electric_gain"


def is_record(path: Path, instrument: str) -> bool:
    """Return whether a file name is a data file of an instrument.

    Only the name is checked. AppleDouble ``._`` twins are rejected.

    Args:
        path (Path): File path.
        instrument (str): Key of `INSTRUMENTS`.

    Returns:
        bool: True for a data file name of `instrument`.

    Raises:
        ValueError: If the instrument is unknown.
    """
    name, stem, suffix = path.name, path.stem, path.suffix
    if name.startswith("._"):
        return False
    if instrument == "lemi423":
        return suffix.lower() == ".b423" and stem.isdigit()
    if instrument == "lemi424":
        return suffix.lower() == ".txt" and len(stem) == 12 and stem.isdigit()
    if instrument == "edl":
        return suffix.upper() in EDL_FILES and EDL_STAMP.search(stem) is not None
    raise ValueError(f"unknown instrument {instrument!r} (know: {', '.join(INSTRUMENTS)})")


def _lemi424_line(path: Path) -> bool:
    """Return whether the first line parses as LEMI-424 data (24 or 16 fields, a year first)."""
    try:
        with open(path, "rb") as f:
            fields = f.readline(512).split()
    except OSError:
        return False
    return len(fields) in LEMI424_FIELDS and fields[0].isdigit() and len(fields[0]) == 4


def detect_instrument(site_dir: str | Path, prefer: str = "lemi423") -> str | None:
    """Detect the instrument whose files a folder holds anywhere below it.

    The folder is walked once. `prefer` is returned as soon as one of its
    files is seen, so a LEMI-423 survey recognises a site by a B423 file
    named by its epoch anywhere under the folder. Otherwise the evidence
    seen decides, `prefer` first, then the `INSTRUMENTS` order. A LEMI-424
    ``.txt`` counts when its first line parses; an EDL folder is recognised
    by a channel file or its ``recorder.ini``.

    Args:
        site_dir (str or Path): Folder to search.
        prefer (str): Instrument to return first, usually the survey's.

    Returns:
        str or None: Key of `INSTRUMENTS`, or None when the folder is not a
        site.
    """
    seen: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(site_dir):
        for name in filenames:
            low = name.lower()  # check the extension before building a Path
            found = ("edl" if low == "recorder.ini" or low[-3:] in _EDL_SUFFIXES else
                     "lemi423" if low.endswith(".b423") else "lemi424" if low.endswith(".txt") else None)
            if found is None or found in seen and found != prefer:
                continue
            path = Path(dirpath) / name
            if low != "recorder.ini" and not is_record(path, found):
                continue
            if found == "lemi424" and not _lemi424_line(path):
                continue
            if found == prefer:
                return found
            seen.add(found)
    return next((i for i in (prefer, *INSTRUMENTS) if i in seen), None)


def b423_files(site_dir: Path) -> list[Path]:
    """List the B423 record files under a folder, sorted by epoch name.

    A B423 file is named by the unix epoch of its first sample, so a name
    that is not a whole number is not a record. Data copied through a Mac
    carry an AppleDouble twin per file (``._1677774771.B423``, a 4 kB
    resource fork); those are skipped with one warning per folder.

    Args:
        site_dir (Path): Site folder, searched recursively.

    Returns:
        list of Path: Record files in time order.
    """
    real, skipped = [], []
    for f in Path(site_dir).rglob("*.B423"):
        (real if f.stem.isdigit() else skipped).append(f)
    if skipped:
        logger.warning(
            f"{Path(site_dir).name}: skipped {len(skipped)} non-record .B423 name(s) "
            f"such as {skipped[0].name!r} (AppleDouble copies from a Mac?)"
        )
    return sorted(real, key=lambda p: int(p.stem))


def file_start(path: Path, instrument: str) -> int:
    """Return the UTC unix second a data file starts at, parsed from its name.

    Raises:
        ValueError: If the instrument is unknown.
    """
    stem = Path(path).stem
    if instrument == "lemi423":
        return int(stem)
    if instrument == "lemi424":
        when = datetime.strptime(stem, "%Y%m%d%H%M")
    elif instrument == "edl":
        when = datetime.strptime(EDL_STAMP.search(stem).group(1), "%y%m%d%H%M%S")
    else:
        raise ValueError(f"unknown instrument {instrument!r}")
    return int(when.replace(tzinfo=timezone.utc).timestamp())


def record_files(site_dir: Path, instrument: str) -> list[Path]:
    """List the data files of an instrument under a folder, sorted by start time.

    For EDL, the channel files of each start are kept together, and when
    ``recorder.ini`` names a station (``station_long_identifier``, read by
    mt-io's `read_recorder_ini`) that some file carries, only that station's
    files are returned (`_edl_own_files`).

    Args:
        site_dir (Path): Site folder, searched recursively.
        instrument (str): Key of `INSTRUMENTS`.

    Returns:
        list of Path: Data files in start order.
    """
    if instrument == "lemi423":
        return b423_files(site_dir)
    found = [Path(d) / n for d, _sub, names in os.walk(site_dir) for n in names
             if is_record(Path(d) / n, instrument)]
    if instrument == "edl":
        found = _edl_own_files(Path(site_dir), found)
    return sorted(found, key=lambda p: (file_start(p, instrument), p.suffix.upper(), str(p)))


def _edl_own_files(site_dir: Path, found: list[Path]) -> list[Path]:
    """Keep the EDL files named for the station that recorder.ini names.

    A PR6-24 keeps writing under the last deployment's name until it is set
    for the new one, and keeps old deployments' day folders. A site's folder
    can therefore hold stamps of another survey's station (which stretch the
    site's span), a few stamps under a placeholder name such as "XX_" (some
    inside the site's own record), or a test recording kept in a subfolder.
    Files of other stations are left out with one warning per site. Station
    names compare case-insensitively without the separating "_" (mt-io's
    `parse_edl_station`).

    Args:
        site_dir (Path): Site folder holding recorder.ini.
        found (list of Path): Candidate EDL files.

    Returns:
        list of Path: The station's files, or all of `found` when
        recorder.ini names no station or no file carries its name.
    """
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import parse_edl_station

    own = str(UoACollection(site_dir).read_recorder_ini().get("station") or "").strip().rstrip("_-").lower()
    if not own:
        return found
    keep, other = [], {}
    for f in found:
        name = (parse_edl_station(f) or "").rstrip("_-")
        if name.lower() == own:
            keep.append(f)
        else:
            other.setdefault(name or "?", []).append(f)
    if not keep:
        logger.warning(f"{site_dir.name}: no EDL file carries recorder.ini's station {own!r}: every file kept")
        return found
    if other:
        logger.warning(f"{site_dir.name}: {sum(len(v) for v in other.values())} EDL file(s) named for another "
                       f"station than recorder.ini's {own!r} left out: "
                       + ", ".join(f"{k} ({len(v)} from "
                                   f"{pd.Timestamp(min(file_start(p, 'edl') for p in v), unit='s'):%Y-%m-%d %H:%M})"
                                   for k, v in sorted(other.items())))
    return keep


def edl_sample_rate(site_dir: Path, files=None) -> float | None:
    """Return the sample rate of an EDL site.

    The rate is read from ``recorder.ini`` (mt-io's
    `UoACollection.read_recorder_ini`). ASCII files carry no header, so
    without recorder.ini the rate comes from consecutive file stamps and
    sample counts (`mt_io.uoa.pr624.infer_sample_rate`, which needs two
    files).

    Args:
        site_dir (Path): Site folder.
        files (list of Path, optional): The site's EDL files; listed with
            `record_files` when None.

    Returns:
        float or None: Sample rate in Hz, or None when neither source gives
        one.
    """
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import infer_sample_rate

    rate = UoACollection(Path(site_dir)).read_recorder_ini().get("sample_rate")
    if rate:
        return float(rate)
    files = files if files is not None else record_files(Path(site_dir), "edl")
    return infer_sample_rate([f for f in files if f.suffix.upper() == ".BX"] or files)


def _lemi424_last_second(path: Path) -> int:
    """Return the UTC second of a LEMI-424 file's last line, reading only the last 4 kB."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        last = f.read().decode(errors="ignore").strip().rsplit("\n", 1)[-1].split()
    when = datetime(*(int(v) for v in last[:6]), tzinfo=timezone.utc)
    return int(when.timestamp())


def span(site_dir: Path, instrument: str, files=None) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """Return the recorded span of a site from its file names.

    LEMI-423: first epoch to the last plus the median spacing (5400 s for
    one file), as `scripts/timing_qc.py` reads it.
    LEMI-424: to the last file's last line plus one second. EDL: to the last
    stamp plus its first channel file's sample count over the rate
    (`edl_sample_rate`).

    Args:
        site_dir (Path): Site folder.
        instrument (str): Key of `INSTRUMENTS`.
        files (list of Path, optional): The site's data files; listed with
            `record_files` when None.

    Returns:
        tuple: ``(start, end, n)``: UTC Timestamps and the number of
        distinct file start stamps.

    Raises:
        FileNotFoundError: If the folder holds no files of the instrument.
    """
    files = files if files is not None else record_files(Path(site_dir), instrument)
    if not files:
        raise FileNotFoundError(f"no {INSTRUMENTS[instrument]['label']} files under {site_dir}")
    starts = sorted({file_start(f, instrument) for f in files})
    if instrument == "lemi423":
        spacing = int(np.median(np.diff(starts))) if len(starts) > 1 else INSTRUMENTS[instrument]["file_seconds"]
        end = starts[-1] + spacing
    elif instrument == "lemi424":
        end = _lemi424_last_second(files[-1]) + 1
    else:
        from mt_io.uoa.pr624 import count_samples

        rate = edl_sample_rate(site_dir, files)
        last = next(f for f in files if file_start(f, instrument) == starts[-1])
        end = starts[-1] + (count_samples(last) / rate if rate else INSTRUMENTS[instrument]["file_seconds"])
    to_ts = lambda s: pd.Timestamp(s, unit="s", tz="UTC")  # noqa: E731
    return to_ts(starts[0]), to_ts(end), len(starts)


def header_facts(site_dir: Path, instrument: str, files: list[Path]) -> dict:
    """Collect the metadata a LEMI-424 or EDL site's files carry.

    Used by `scripts/new_survey.py`. LEMI-424: the reader's first and last
    line (`LEMI424.read_metadata`) give the GPS position, elevation and
    rate; serial and firmware come from the ``.inf`` header the logger
    writes at deployment ("%LEMI424 #0160", "%FIRMWARE Ver.1.4"), which
    mt-io does not read. EDL: the rate (`edl_sample_rate`) and the
    recorder.ini high-gain flags; the files carry no position and no serial.

    Args:
        site_dir (Path): Site folder.
        instrument (str): ``"lemi424"`` or ``"edl"``.
        files (list of Path): The site's data files.

    Returns:
        dict: ``sample_rate``, ``columns`` (the reader's names for what
        ingest reads) and, as available, ``latitude``, ``longitude``,
        ``elevation``, ``serial``, ``firmware``, ``high_gain`` and
        ``problem`` (a message for the user).

    Raises:
        ValueError: For any other instrument.
    """
    if instrument == "lemi424":
        from mt_io.lemi.lemi424 import LEMI424

        head = LEMI424(files[0])
        head.read_metadata()
        facts = {"sample_rate": float(head.sample_rate),
                 "columns": ["bx", "by", "bz", *LEMI424_ELECTRICS]}
        if head.latitude is not None and (head.latitude, head.longitude) != (0, 0):
            facts.update(latitude=round(float(head.latitude), 6), longitude=round(float(head.longitude), 6),
                         elevation=round(float(head.elevation), 1))
        else:
            facts["problem"] = "no GPS position in the first LEMI-424 file"
        for inf in sorted(Path(site_dir).rglob("*.inf"))[:1]:
            text = inf.read_text(errors="ignore")
            serial = re.search(r"%LEMI424\s*#\s*0*(\d+)", text)
            firmware = re.search(r"%FIRMWARE\s+Ver\.?\s*(\S+)", text)
            facts.update(serial=serial and serial.group(1), firmware=firmware and firmware.group(1))
        return facts
    if instrument == "edl":
        present = {f.suffix.upper() for f in files}
        return {"sample_rate": edl_sample_rate(site_dir, files),
                "columns": [comp for suffix, comp in EDL_FILES.items() if suffix in present],
                "high_gain": recorder_ini_high_gain(site_dir),
                "problem": "EDL files carry no position: set it from the field sheet"}
    raise ValueError(f"header_facts reads lemi424 and edl, not {instrument!r}")


def read_run(instrument: str, files: list[Path], site, site_dir: Path, calibration: Path | None = None):
    """Read one contiguous group of a LEMI-424 or EDL site's files into a RunTS.

    LEMI-423 files are read in `mtproc.ingest.ingest_site`.

    LEMI-424: the reader is given every electric column
    (`LEMI424_ELECTRICS`), and the station id, which the reader leaves
    empty, is set. No dipole length is applied and the reader's units are
    kept.

    EDL: the reader is given the rate from `edl_sample_rate`, the site's
    dipole lengths, its azimuths when `flip_reversed_dipoles` treats a
    180/270 deg azimuth as a reversed pair (the reader's dipole filter then
    carries the sign; nominal 0/90 otherwise), and the position when
    declared. The x10 terminal box is the reader's default. The magnetic
    sensors are the site's `sensor_type` (`EDL_SENSORS`): "bartington"
    (Mag-03 fluxgates, the long-period setup and the reader's default) or
    "lemi120" (induction coils, the broadband setup), whose response file
    `calibration` is passed to the reader for hx, hy and hz. A coil read with
    the fluxgate chain comes out 2800 times too large with no coil response.
    When the declared `electric_gain` (`edl_electric_gain`) is not 1.0,
    `ELECTRIC_GAIN_FILTER` is appended to the ex and ey chains
    (`add_electric_gain`). Read without its declared gain g, a site's
    apparent resistivity comes out g squared times too large (100 times
    for a gain of 10).

    Args:
        instrument (str): ``"lemi424"`` or ``"edl"``.
        files (list of Path): Files of one contiguous run.
        site (SiteConfig): Site settings.
        site_dir (Path): Site folder.
        calibration (Path, optional): The site's resolved `calibration_fn`,
            required for sensor_type lemi120.

    Returns:
        RunTS: The run as mt-io reads it.

    Raises:
        ValueError: If the EDL sample rate is unknown, a magnetic channel
            lacks the expected sensor response, the sensor type is unknown,
            or the instrument is neither lemi424 nor edl.
        FileNotFoundError: If sensor_type lemi120 has no response file.
    """
    files = [Path(f) for f in files]
    if instrument == "lemi424":
        from mt_io.lemi.lemi424 import read_lemi424

        run = read_lemi424(files, e_channels=list(LEMI424_ELECTRICS))
        run.station_metadata.id = site.name
        return run
    if instrument == "edl":
        from mt_io.uoa.pr624 import read_uoa

        rate = edl_sample_rate(site_dir)
        if rate is None:
            raise ValueError(f"{site.name}: EDL sample rate unknown (no recorder.ini, and the file "
                             f"stamps do not give one)")
        flip = site.flip_reversed_dipoles
        kwargs = dict(sample_rate=rate, station_id=site.name,
                      dipole_length_ex=site.dipole_length_ex, dipole_length_ey=site.dipole_length_ey,
                      ex_azimuth=site.azimuth_ex if flip else 0.0, ey_azimuth=site.azimuth_ey if flip else 90.0)
        kwargs.update({k: getattr(site, k) for k in ("latitude", "longitude", "elevation")
                       if getattr(site, k) is not None})
        sensor = edl_sensor(site)
        if sensor == "lemi120":
            if calibration is None or not Path(calibration).is_file():
                raise FileNotFoundError(f"{site.name}: sensor_type lemi120 needs the coils' response file "
                                        f"(calibration_fn), got {calibration}")
            kwargs.update(sensor_type="lemi120", **{f"calibration_fn_{c}": str(calibration) for c in ("bx", "by", "bz")})
        run = read_uoa(files, **kwargs)
        for comp in ("hx", "hy", "hz"):
            # a coil file the reader cannot read is logged and leaves the channel with no chain
            names = [f["applied_filter"]["name"] for f in run.dataset[comp].attrs.get("filters") or []] \
                if comp in run.dataset else None
            if names is not None and not any(n.startswith(EDL_SENSORS[sensor]) for n in names):
                raise ValueError(f"{site.name} {comp}: no {sensor} response in the reader's chain {names}")
        add_electric_gain(run, edl_electric_gain(site), site.name)
        return run
    raise ValueError(f"read_run reads lemi424 and edl, not {instrument!r}")


def edl_electric_gain(site) -> float:
    """Return an EDL site's declared electric chain gain, 1.0 (no filter) when unset."""
    value = getattr(site, "electric_gain", None)
    return 1.0 if value is None else float(value)


def add_electric_gain(run, gain: float, tag: str = "") -> list[str]:
    """Append `ELECTRIC_GAIN_FILTER` to the ex and ey filter chains of a run.

    The samples are left unchanged. The coefficient filter (microVolt in
    and out) goes into ``run.filters`` and each channel's applied-filter
    list, as `mtproc.ingest._apply_h_scale` adds its scale, so the archive
    carries it and calibration divides by it.

    Args:
        run (RunTS): Run to modify in place.
        gain (float): Electric chain gain. A gain of 1.0, the default when
            none is declared, adds nothing.
        tag (str): Label for the caller; not used in the filter.

    Returns:
        list of str: The electric channels the filter was added to (ex, ey,
        whichever the run carries).
    """
    if not gain or float(gain) == 1.0:
        return []
    from mt_metadata.timeseries.filters import CoefficientFilter

    coef = CoefficientFilter()
    coef.name = ELECTRIC_GAIN_FILTER
    coef.gain = float(gain)
    coef.units_in = "microVolt"
    coef.units_out = "microVolt"
    coef.comments = "electric chain gain declared from the field notes"
    run.filters[coef.name] = coef
    done = []
    for comp in ("ex", "ey"):
        if comp not in run.dataset:
            continue
        chain = list(run.dataset[comp].attrs.get("filters") or [])
        chain.append({"applied_filter": {"applied": True, "name": coef.name, "stage": len(chain) + 1}})
        run.dataset[comp].attrs["filters"] = chain
        done.append(comp)
    return done


def recorder_ini_high_gain(site_dir: Path) -> list[str] | None:
    """List the EDL channels flagged ``channel_n_high_gain=1`` in recorder.ini.

    EDM 021 4.2.8 defines one flag per channel, default low. mt-io's
    `UoACollection.read_recorder_ini` folds the six into one boolean
    (docs/upstream_issues.md 21), so the first recorder.ini under
    `site_dir`, the one mt-io takes, is parsed here. Channel n is the file
    extension its ``channel_n_long_id`` names (BX .. EY, the reader's
    hx .. ey), else UoA's order 0-4 = BX BY BZ EX EY. The result is
    informational: `electric_gain` records the electric chain gain from the
    field notes, which is separate from this PR6-24 pre-amplifier setting,
    and `mtproc.ingest._electric_gain` uses the result for a warning.

    Args:
        site_dir (Path): Site folder.

    Returns:
        list of str or None: Flagged channels in hx, hy, hz, ex, ey order;
        an empty list when every flag is 0; None when there is no readable
        recorder.ini or it sets no gain flag.
    """
    import configparser

    found = sorted(Path(site_dir).rglob("recorder.ini"))
    if not found:
        return None
    parser = configparser.ConfigParser(strict=False)
    try:
        parser.read(found[0], encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError) as exc:
        logger.warning(f"could not read {found[0]}: {exc}")
        return None
    if not parser.has_section("recorder"):
        return None
    section = parser["recorder"]
    order = list(EDL_FILES)  # .BX .BY .BZ .EX .EY
    flags = {}
    for n in range(6):
        flag = section.get(f"channel_{n}_high_gain")
        if flag is None:
            continue
        ident = str(section.get(f"channel_{n}_long_id") or (order[n][1:] if n < len(order) else "")).strip()
        comp = EDL_FILES.get("." + ident.upper())
        if comp is not None:
            flags[comp] = flag.strip() not in ("", "0")
    if not flags:
        return None
    return [c for c in INSTRUMENTS["edl"]["channels"] if flags.get(c)]


def edl_sensor(site) -> str:
    """Return an EDL site's magnetic sensor type.

    Args:
        site (SiteConfig): Site settings.

    Returns:
        str: Key of `EDL_SENSORS`, the site's `sensor_type` or
        "bartington" when unset.

    Raises:
        ValueError: If `sensor_type` is not a key of `EDL_SENSORS`.
    """
    sensor = str(getattr(site, "sensor_type", None) or "bartington").strip().lower()
    if sensor not in EDL_SENSORS:
        raise ValueError(f"{site.name}: sensor_type {sensor!r} is not one of {', '.join(EDL_SENSORS)}")
    return sensor
