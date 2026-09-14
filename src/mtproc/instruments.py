"""The recorders mtproc reads, and how a folder of raw files says which one it holds.

A site's instrument is a fact of its files: the survey
names a default (`instrument:` at the top of survey.yaml) and a site whose
folder holds another recorder's files is that recorder, detected here and
written by `scripts/new_survey.py` as the site's own `instrument:`.

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
             whose PR6-24 configs were not kept (Stuart Shelf 2009), known
             only from the field notes. It gets one more filter here, on ex
             and ey, of that gain (`ELECTRIC_GAIN_FILTER`)

Nothing here imports mt-io at module load (`mtproc.survey` imports this);
the readers are imported where they are used. File names carry each file's
start in UTC (`file_start`), which is all the run splitting and the spans
need.
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
# an EDL site's magnetic sensors (`sensor_type:`, mt_io.uoa.pr624's own names) -> the prefix of
# the response filter the reader puts on hx/hy/hz for them
EDL_SENSORS = {"bartington": "uoa_bartington", "lemi120": "lemi_120"}
_EDL_SUFFIXES = {s.lower() for s in EDL_FILES}
# An EDL site's electric chain may carry extra gain between the dipoles and the recorded values,
# beyond what the reader already models (the x10 terminal box): hardwired at the field terminal
# junction box, and for a survey whose PR6-24 configs were not kept (Stuart Shelf 2009), known only
# from the field notes. `SiteConfig.electric_gain` (default 1.0, no filter) declares it; `read_run`
# folds it into this filter on ex and ey: forward, as the reader's own gains are (input microVolt ->
# stored words), so calibration divides by it and the channels come out that many times smaller.
# The archive keeps the words as stored.
ELECTRIC_GAIN_FILTER = "uoa_electric_gain"


def is_record(path: Path, instrument: str) -> bool:
    """Whether `path`'s name is a data file of `instrument` (the name only; AppleDouble `._` twins never are)."""
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
    """Whether the file's first line is one the LEMI-424 reader parses (24 or 16 fields, a date first)."""
    try:
        with open(path, "rb") as f:
            fields = f.readline(512).split()
    except OSError:
        return False
    return len(fields) in LEMI424_FIELDS and fields[0].isdigit() and len(fields[0]) == 4


def detect_instrument(site_dir: str | Path, prefer: str = "lemi423") -> str | None:
    """The instrument whose files `site_dir` holds anywhere below it, or None (not a site).

    One walk. `prefer` (the survey's instrument) wins as soon as one of its
    files is seen, so a LEMI-423 survey finds its sites exactly as the old
    rule did (a B423 file named by its epoch anywhere under the folder);
    otherwise the evidence seen decides, `prefer` first, then the
    `INSTRUMENTS` order: a LEMI-424 `.txt` counts only when its first line
    parses, an EDL folder by a channel file or its `recorder.ini`.
    """
    seen: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(site_dir):
        for name in filenames:
            low = name.lower()  # a cheap look at the extension before any Path is made
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
    """Every real B423 record file under `site_dir`, sorted by its epoch name.

    A B423 file is named by the unix epoch of its first sample, so a name
    that is not a whole number is not a record: data copied through a Mac
    arrives with an AppleDouble twin per file (`._1677774771.B423`, a 4 kB
    resource fork), and those are skipped with one warning per folder.
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
    """The UTC unix second a data file starts at, from its name."""
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
    """Every data file of `instrument` under `site_dir`, by start (EDL: the channel files of each start together).

    EDL: only the files named for the station `recorder.ini` names
    (`station_long_identifier`, mt-io's `read_recorder_ini`), when it names one
    and any file carries it (`_edl_own_files`).
    """
    if instrument == "lemi423":
        return b423_files(site_dir)
    found = [Path(d) / n for d, _sub, names in os.walk(site_dir) for n in names
             if is_record(Path(d) / n, instrument)]
    if instrument == "edl":
        found = _edl_own_files(Path(site_dir), found)
    return sorted(found, key=lambda p: (file_start(p, instrument), p.suffix.upper(), str(p)))


def _edl_own_files(site_dir: Path, found: list[Path]) -> list[Path]:
    """The EDL files whose name carries the station recorder.ini names; all of them when none does.

    A PR6-24 keeps writing under the last deployment's name until it is set
    for the new one, and keeps old deployments' day folders: Hillside's HSSL09
    folder holds 115 stamps of another survey's PLB03 from 2012-04-29 (its span
    read 1602.7 h), hs058 four stamps of "XX_" at 01:48-02:47 (one inside its
    own record), hs061 a test recording "HStest_" under old/ with its own
    files' stamps. Those are left out, with one warning per site. The station
    names compare case-insensitively without the separating "_" (mt-io's
    `parse_edl_station`).
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
    """An EDL site's rate: `recorder.ini` (mt-io's `UoACollection.read_recorder_ini`), else the file spacing.

    ASCII files carry no header; with no recorder.ini the rate comes from
    consecutive file stamps and sample counts (`mt_io.uoa.pr624.infer_sample_rate`,
    which needs two files). None when neither says.
    """
    from mt_io.uoa import UoACollection
    from mt_io.uoa.pr624 import infer_sample_rate

    rate = UoACollection(Path(site_dir)).read_recorder_ini().get("sample_rate")
    if rate:
        return float(rate)
    files = files if files is not None else record_files(Path(site_dir), "edl")
    return infer_sample_rate([f for f in files if f.suffix.upper() == ".BX"] or files)


def _lemi424_last_second(path: Path) -> int:
    """The UTC second of a LEMI-424 file's last line (its tail, not the whole file)."""
    with open(path, "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 4096))
        last = f.read().decode(errors="ignore").strip().rsplit("\n", 1)[-1].split()
    when = datetime(*(int(v) for v in last[:6]), tzinfo=timezone.utc)
    return int(when.timestamp())


def span(site_dir: Path, instrument: str, files=None) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    """(start, end, number of files or file stamps) of a site's recording, from its file names.

    LEMI-423: first epoch to the last plus the median spacing (5400 s for one
    file), as `scripts/timing_qc.py` and the MATLAB app read it. LEMI-424:
    to the last file's last line plus one second. EDL: to the last stamp plus
    its first channel file's sample count over the rate (`edl_sample_rate`).
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
    """What a LEMI-424 or EDL site's own files say, for `scripts/new_survey.py`.

    LEMI-424: the reader's first and last line (`LEMI424.read_metadata`) for
    the GPS position and elevation and the rate; serial and firmware from the
    `.inf` header the logger writes at deployment ("%LEMI424 #0160",
    "%FIRMWARE Ver.1.4"; mt-io has no reader for it). EDL: the rate
    (`edl_sample_rate`); the files carry no position and no serial. `columns`
    are the reader's names for what ingest reads.
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
    """One contiguous group of a LEMI-424 or EDL site's files -> a RunTS, through the mt-io reader.

    (LEMI-423 is read in `mtproc.ingest.ingest_site` itself, unchanged.)
    LEMI-424: every electric column (`LEMI424_ELECTRICS`) and the station id,
    which the reader leaves empty; nothing else is touched -- no dipole
    length, the reader's units. EDL: the rate from `edl_sample_rate`, the
    site's dipole lengths, and its azimuths when `flip_reversed_dipoles` says a
    180/270 degree azimuth is a reversed pair (the reader's dipole filter then
    carries the sign; nominal 0/90 otherwise), the position when declared.
    The x10 terminal box is the reader's default. The magnetic sensors are the
    site's `sensor_type` (`EDL_SENSORS`): "bartington" (Mag-03 fluxgates, the
    long-period setup; also what no `sensor_type` means, the reader's default)
    or "lemi120" (induction coils, the broadband setup), whose response file
    `calibration` (the site's resolved `calibration_fn`) goes to the reader for
    hx, hy and hz -- a coil read with the fluxgate chain comes out 2800 times
    too large with no coil response (Hillside). The site's declared
    `electric_gain` (`edl_electric_gain`), when not 1.0, gets `ELECTRIC_GAIN_FILTER`
    at the end of ex and ey's chain (`add_electric_gain`): Stuart Shelf 2009's
    electric chain gain, declared from the field notes, is 10.0, and read
    without it its rho came out 100x the 2009 result.
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
            # the reader logs a coil file it cannot read and leaves the channel with no chain
            names = [f["applied_filter"]["name"] for f in run.dataset[comp].attrs.get("filters") or []] \
                if comp in run.dataset else None
            if names is not None and not any(n.startswith(EDL_SENSORS[sensor]) for n in names):
                raise ValueError(f"{site.name} {comp}: no {sensor} response in the reader's chain {names}")
        add_electric_gain(run, edl_electric_gain(site), site.name)
        return run
    raise ValueError(f"read_run reads lemi424 and edl, not {instrument!r}")


def edl_electric_gain(site) -> float:
    """An EDL site's declared electric chain gain (`SiteConfig.electric_gain`), 1.0 (no filter) when unset."""
    value = getattr(site, "electric_gain", None)
    return 1.0 if value is None else float(value)


def add_electric_gain(run, gain: float, tag: str = "") -> list[str]:
    """Append `ELECTRIC_GAIN_FILTER` (`gain`, microVolt in and out) to ex and ey's chain in `run`.

    The samples are not touched: the filter goes into `run.filters` and each
    channel's applied-filter list, as `mtproc.ingest._apply_h_scale` adds its
    scale, so the archive carries it and calibration divides by it. `gain` of
    1.0 (the default -- no gain declared) adds nothing. Returns the electric
    channels this run has data for (ex, ey, whichever the run carries).
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
    """The EDL channels a site's recorder.ini flags `channel_n_high_gain=1` on, or None.

    EDM 021 4.2.8: one flag per channel, default low. mt-io's
    `UoACollection.read_recorder_ini` folds the six into one boolean nothing
    reads (docs/upstream_issues.md 21), so the file is read here, the first
    recorder.ini under `site_dir` as mt-io takes it: channel n is the file
    extension its `channel_n_long_id` names (BX .. EY, the reader's hx .. ey),
    else UoA's order 0-4 = BX BY BZ EX EY. None when there is no recorder.ini
    or it sets no gain; [] when every flag is 0. Informational only:
    `electric_gain` is a field-notes fact about the electric chain, not
    this PR6-24 pre-amplifier setting, so
    `mtproc.ingest._electric_gain` only warns with what this returns, never
    sets `electric_gain` from it.
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
    """An EDL site's magnetic sensors, a key of `EDL_SENSORS`: its `sensor_type`, "bartington" when unset."""
    sensor = str(getattr(site, "sensor_type", None) or "bartington").strip().lower()
    if sensor not in EDL_SENSORS:
        raise ValueError(f"{site.name}: sensor_type {sensor!r} is not one of {', '.join(EDL_SENSORS)}")
    return sensor
