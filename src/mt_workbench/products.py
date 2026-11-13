# -*- coding: utf-8 -*-
"""
Transfer-function products: the frame metadata and the three files of a row

Every product is kept in the frame the sensors were laid out in. The survey says which north the sensors were
laid out to: survey.yaml's `layout_north` (`defaults:` or a site's own
entry), "magnetic" (the default) or "geographic", gives the station's
``orientation.reference_frame``, geomagnetic or geographic, for every
reader (`set_reference_frame`; the LEMI-424 reader's own default is
geographic). The site's declination is stored with every product.
`set_declination` writes the declination (value in degrees east of
geographic north, model, epoch) into a TF's station metadata,
`apply_site_declination` does so from a survey.yaml site entry
(`mt_workbench.survey.SiteConfig`: `declination`, `declination_model`,
`declination_epoch`) when the entry carries one, and `apply_site_frame`
sets both the frame and the declination. `match_coordinate_system` sets
``transfer_function.coordinate_system`` to the reference frame, so the
EDI's HEAD (COORDINATE_SYSTEM) and INFO
(transfer_function.coordinate_system) say the same thing.

The rotation convention. A geomagnetic product whose declination is set
has its x-axis at azimuth D, the declination, clockwise (east positive)
from geographic north (`x_azimuth`). The EDI states this as ZROT = TROT = D
at every period, with the data left as estimated. This matches the
convention Geotools writes: its own rotation by t writes ZROT t and
Z' = R Z R^T with R = [[cos t, sin t], [-sin t, cos t]], and a ZROT 0 file
round-trips unchanged (export test); how Geotools treats a
non-zero ZROT on import is not yet tested. Geotools drops
COORDINATE_SYSTEM and zeroes AZM on export but keeps the INFO block, so
the frame is also stated in words there (`frame_info_lines`,
``mt_workbench.frame``, ``mt_workbench.rotation`` and the three
``mt_workbench.declination*`` lines). A fluxgate site whose horizontal pair
was turned onto magnetic north at ingest (survey.yaml `rot_h`, a correction
of the sensor's frame recorded in the archive's run comments, not a
rotation of the estimate) gets ``mt_workbench.rot_h`` with the angle, and
the sidecar's frame record its ``rot_h`` (`tf_rot_h`). The EMTF XML states it in its own
fields (`xml_copy`): Site Orientation angle_to_geographic_north D and each
horizontal channel's orientation its measurement azimuth plus D (Hx D,
Hy 90 + D, Ex D, Ey 90 + D). A geographic layout, or a geomagnetic one
whose declination is unset, gives ZROT 0 and angle 0.

The survey.yaml block `products: {zrot: declination | zero}` (`zrot_rule_of`)
chooses what a geomagnetic product with a declination writes as ZROT and
TROT. ``declination`` (the default) is the convention above, unchanged.
``zero`` (the Queensland convention) writes ZROT =
TROT = 0 (`edi_azimuth`), COORDINATE_SYSTEM geomagnetic in HEAD and INFO,
the DECLINATION lines with the site's value, model and epoch, INFO lines
saying the declination is recorded and not applied, and
``mt_workbench.zrot_rule=zero`` (`set_zrot_rule`, read back by
`tf_zrot_rule`, so a merge of such products keeps it); the sidecar's frame
record carries ``zrot_rule`` and the XML's Notes say so, while the XML's
own orientation fields keep the true azimuth D. A read-back EDI's frame
lines (the reader's bare keys ``frame=``, ``rotation=``, ...) are replaced
on a re-write, never repeated beside the new ones. `instrument_info_lines`
and `apply_instruments` carry a site's instrument identity from
<survey folder>/instruments.csv into INFO and the TF's run and
channel metadata.

`write_products` writes a row's three files from one TF, under one stem:

* ``<stem>.edi`` (`edi_copy`: ZROT and the INFO frame lines);
* ``<stem>.xml``, the EMTF XML of mt_metadata's writer (`xml_copy`), whose
  Notes state the frame, the convention, the declination and whether the
  residual and inverse signal covariances (RESIDCOV, INVSIGCOV) are carried
  (`frame_note`), and, when the TF's INFO lines carry the instruments'
  registry DOIs (`pid_info_lines`, one ``mt_workbench.instrument_pid_<role>_<instrument>``
  line each), a sentence naming them as https://doi.org/ links
  (`pid_sentence`);
* ``<stem>.h5``, a standalone MTH5 file created fresh, holding the survey and
  station metadata and this TF (`mth5.mth5.MTH5.add_transfer_function`),
  which `mth5.mth5.MTH5.get_transfer_function` reads back.

It then records the product in its folder's index from the sidecar beside
the EDI, when there is one (`mt_workbench.tf_index.add`; the View EDIs list
reads the index instead of every sidecar).

The measurement lines. aurora's TF carries channels with no geometry
(measurement azimuth 0 and dipole length 0 on every channel), so the EDI's
EMEAS and HMEAS lines read AZM=0.00 with no electrode coordinates though
the archive holds the azimuths and lengths (docs/workbench_issues.md 52).
`archive_geometry` reads each channel's geometry from an archive (the
first run of its station: measurement azimuth and tilt, an electric
channel's dipole length and electrode positions), and `set_channel_geometry`
writes it into every run of a TF's station metadata; `edi_copy`,
`write_edi` and `write_products` take it as ``geometry`` (None leaves the
TF's own channels, as before). An electric line whose archive holds no
electrode positions is written from the centre: negative end at (0, 0),
positive end at the dipole length along the measurement azimuth (EMEAS X,
Y and X2, Y2, x north and y east in metres); hz is written vertical (DIP
90) when the archive gives it no tilt. The azimuths are the archive's,
which are the resolved ones (ex 0 and ey 90 after the survey's polarity and
swap corrections; theta_d for a diagonal site), from magnetic north in a
geomagnetic frame.

`product_names` gives the three file names a sidecar records (keys edi,
xml, h5). Each format is written from its own copy of the TF, since
mt_metadata's EDI writer sets ``translated_azimuth`` on the electric
channels it writes, which the XML writer would then take as their
orientation.

aurora regresses each output channel on the inputs separately, so the
residual covariance's Ex-Ey cross term is not estimated (NaN or 0 in the
TF). mt_metadata's XML writer writes every zero as the EMPTY fill 1e32;
`write_xml` writes that cross term as 0 instead (`fill_residcov_cross`)
and the Notes say so, and `write_h5` writes it as 0 with the same
statement in the station comments.

mt_metadata's EMTF XML writer has a limit the Notes record: its Site
Location Declination element keeps the value and the whole year only (no
model). It writes 0 at 1995 when none is stored; `write_xml` removes the
element then, and `frame_record` gives the sidecar null declination keys,
as the EDI writes no DECLINATION line. `write_xml` keeps in its copy only
the channels the TF holds data for, since the writer fails on an aurora TF
whose runs disagree on hz. The writer also takes each ";"-piece of a run
comment that holds a ":" as an attribute path and its value, and raises on
a key with a dot (upstream issues 48 and 82), so the copy's run comments
have the dots of their keys replaced (`dot_free_comment_keys`); the
values, and the archive, keep theirs.

A station id may hold a hyphen (KD-Q5): mt_metadata's Station id admits
it and its Run id does not, and its EDI and EMTF XML code builds a
placeholder run "<station>a" (upstream issue 86). `write_edi` and
`write_xml` write, and `read_tf` reads, inside `hyphenated_station_ids`,
which makes that placeholder run id admissible ("KD_Q5a") and keeps the
hyphen of the EDI's DATAID on reading; the station id and DATAID stay as
declared.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import copy
import os
import re
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from loguru import logger

from mt_workbench import tf_index

# the product formats of a row, by sidecar key, and their suffixes
PRODUCT_SUFFIXES = {"edi": ".edi", "xml": ".xml", "h5": ".h5"}
# survey.yaml's layout_north -> the station's orientation.reference_frame
LAYOUT_FRAMES = {"magnetic": "geomagnetic", "geographic": "geographic"}
DEFAULT_LAYOUT_NORTH = "magnetic"
# the INFO keys `frame_info_lines` writes; a TF read back from an EDI carries them, and they are replaced
FRAME_INFO_KEYS = ("mt_workbench.frame", "mt_workbench.rotation", "mt_workbench.declination",
                   "mt_workbench.declination_model", "mt_workbench.declination_epoch", "mt_workbench.rot_h",
                   "mt_workbench.rot_h_parts", "mt_workbench.h_tilt", "mt_workbench.zrot_rule")
# survey.yaml `products: {zrot: ...}`: what a geomagnetic product with a declination writes as ZROT and TROT.
# "declination" (the default; Victoria, Tasmania): the declination, the x-axis azimuth from geographic north.
# "zero" (the Queensland convention): 0, the frame stated geomagnetic, the declination recorded only.
ZROT_RULES = ("declination", "zero")
ZROT_KEY = "mt_workbench.zrot_rule"
INSTRUMENTS_CSV = "instruments.csv"  # <survey folder>/instruments.csv
# start of the run, channel and station comment line mt_workbench.ingest._rot_h writes for a site declared
# `rot_h` (mt_workbench.survey.SiteConfig.rot_h), followed by the angle in degrees and " deg"
ROT_H_PREFIX = "rot_h: "
# start of the run, channel and station comment line mt_workbench.ingest._rot_h_parts writes for each part of a site
# declared `rot_h_parts`: "rot_h_part: <angle> deg over <start> .. <end> ..." (times compact, YYYYmmddTHHMMSSZ)
ROT_H_PARTS_PREFIX = "rot_h_part: "
# start of the run, channel and station comment line mt_workbench.ingest._h_tilt writes for a site declared `h_tilt`
# (mt_workbench.survey.SiteConfig.h_tilt): "h_tilt: <rx> <ry> <rz> deg rotation vector applied at ingest ..."
H_TILT_PREFIX = "h_tilt: "


def parse_h_tilt(piece: str):
    """Return [rx, ry, rz] of one "h_tilt: <rx> <ry> <rz> deg ..." line, None if it is not one."""
    import re

    m = re.match(re.escape(H_TILT_PREFIX) + r"(-?[0-9.]+(?:e-?[0-9]+)?) (-?[0-9.]+(?:e-?[0-9]+)?) "
                 r"(-?[0-9.]+(?:e-?[0-9]+)?) deg", piece.strip())
    return [float(m.group(i)) for i in (1, 2, 3)] if m else None


def parse_rot_h_part(piece: str):
    """Return (start ISO, end ISO, angle) of one "rot_h_part: <a> deg over <s> .. <e> ..." line, None if it is not one."""
    import re

    m = re.match(re.escape(ROT_H_PARTS_PREFIX) + r"(-?[0-9.]+) deg over (\d{8}T\d{6}Z) \.\. (\d{8}T\d{6}Z)", piece)
    if not m:
        return None
    iso = lambda c: f"{c[:4]}-{c[4:6]}-{c[6:8]}T{c[9:11]}:{c[11:13]}:{c[13:15]}Z"  # noqa: E731
    return [iso(m.group(2)), iso(m.group(3)), float(m.group(1))]
# mt_metadata's EDI writer puts a processing parameter on the line
# "    transfer_function.processing_parameters.<line>"; a written INFO line stays under INFO_MAX characters
INFO_PREFIX = "    transfer_function.processing_parameters."
INFO_MAX = 160
# the horizontal channels whose XML orientation is the measurement azimuth plus the declination
HORIZONTAL = ("ex", "ey", "hx", "hy")
CROSS_NOTE = ("Residual cross term Ex-Ey not estimated (aurora regresses each output channel separately): "
              "written as 0; rotated errors assume zero output-side correlation.")
# a Z.RESIDCOV block of the written XML, and an Ex-Ey or Ey-Ex value in it holding the EMPTY fill
_RESIDCOV = re.compile(r"<Z\.RESIDCOV\b.*?</Z\.RESIDCOV>", re.S)
_EMPTY_CROSS = re.compile(r'(<value output="(E[xy])" input="(E[xy])">)\s*1(?:\.0*)?e\+32\s+1(?:\.0*)?e\+32\s*(</value>)')
# the Declination element of the written XML's Site Location, with the line break before it
_DECLINATION = re.compile(r"\r?\n[ \t]*<Declination\b[^>]*>[^<]*</Declination>")
# a character mt_metadata's Run id pattern (^[a-zA-Z0-9_]*$) refuses
_RUN_ID_REFUSED = re.compile(r"[^A-Za-z0-9_]")
# the INFO lines of the instrument registry DOIs (`pid_info_lines`): "mt_workbench.instrument_pid_<path>=<doi>",
# the path "<role>_<instrument>" with underscores only, since mt_metadata's EDI reader keeps the last part of
# a dotted key (docs/upstream_issues.md 115); a TF read back from an EDI carries "instrument_pid_<path>"
PID_INFO_KEY = "instrument_pid_"
# the instrument roles of mt_workbench.survey.Survey.instrument_pids, longest first for parsing a path
PID_INSTRUMENTS = ("logger_hx_hy", "logger", "sensor_hx", "sensor_hy", "sensor_hz", "electrode", "platform")
DOI_RESOLVER = "https://doi.org/"


def product_paths(edi_path: str | Path) -> dict[str, Path]:
    """Return the three product paths of a row from its EDI path.

    Args:
        edi_path (str or Path): The row's EDI.

    Returns:
        dict: ``{"edi": Path, "xml": Path, "h5": Path}``, same folder and stem.
    """
    edi_path = Path(edi_path)
    return {key: edi_path.with_suffix(suffix) for key, suffix in PRODUCT_SUFFIXES.items()}


def product_names(edi_path: str | Path) -> dict[str, str]:
    """Return the three product file names of a row, the sidecar's edi, xml and h5 keys."""
    return {key: path.name for key, path in product_paths(edi_path).items()}


def _text(value) -> str:
    """Return an enum's value, or the text of anything else."""
    return str(getattr(value, "value", value))


def layout_frame(layout_north: str | None) -> str:
    """Return the reference frame of a survey.yaml `layout_north`.

    Args:
        layout_north (str or None): "magnetic" or "geographic"; None means
            the default, magnetic.

    Returns:
        str: "geomagnetic" or "geographic".

    Raises:
        ValueError: For any other value.
    """
    key = DEFAULT_LAYOUT_NORTH if layout_north is None else str(layout_north).strip().lower()
    if key not in LAYOUT_FRAMES:
        raise ValueError(f"layout_north {layout_north!r}: expected one of {', '.join(LAYOUT_FRAMES)}")
    return LAYOUT_FRAMES[key]


def set_reference_frame(station_metadata, site) -> str | None:
    """Set a station's ``orientation.reference_frame`` from a site's `layout_north`.

    Args:
        station_metadata: An mt_metadata Station.
        site: A `mt_workbench.survey.SiteConfig`, or any object with
            `layout_north`; None leaves the metadata as it was.

    Returns:
        str or None: The frame set, or None when `site` is None.
    """
    if site is None:
        return None
    frame = layout_frame(getattr(site, "layout_north", None))
    station_metadata.orientation.reference_frame = frame
    return frame


def set_declination(station_metadata, value: float, model: str | None = None, epoch=None) -> None:
    """Set the declination of a station's metadata.

    Args:
        station_metadata: An mt_metadata Station (``tf.station_metadata``
            or an MTH5 station group's metadata).
        value (float): Declination in degrees, east positive.
        model (str, optional): Field model, e.g. "IGRF-14"; left as it is
            when None.
        epoch (float or str, optional): Decimal year the value is for;
            stored as text with two decimals ("2023.53"); left as it is when
            None.
    """
    declination = station_metadata.location.declination
    declination.value = float(value)
    if model is not None:
        declination.model = str(model)
    if epoch is not None:
        declination.epoch = f"{float(epoch):.2f}"


def apply_site_declination(station_metadata, site) -> bool:
    """Copy a survey.yaml site's declination into station metadata.

    Args:
        station_metadata: An mt_metadata Station.
        site: A `mt_workbench.survey.SiteConfig`, or any object with
            `declination`, `declination_model` and `declination_epoch`.

    Returns:
        bool: True when the site carries a declination and it was set;
        False when its `declination` is None (unset), leaving the metadata
        as it was.
    """
    value = getattr(site, "declination", None) if site is not None else None
    if value is None:
        return False
    set_declination(station_metadata, value, getattr(site, "declination_model", None),
                    getattr(site, "declination_epoch", None))
    return True


def apply_site_frame(station_metadata, site) -> bool:
    """Set a station's reference frame and declination from a survey.yaml site.

    `set_reference_frame` then `apply_site_declination`; the channel
    azimuths stay as recorded.

    Args:
        station_metadata: An mt_metadata Station.
        site: A `mt_workbench.survey.SiteConfig`; None leaves the metadata
            as it was.

    Returns:
        bool: True when a declination was set (`apply_site_declination`).
    """
    set_reference_frame(station_metadata, site)
    return apply_site_declination(station_metadata, site)


def match_coordinate_system(tf) -> str:
    """Set ``transfer_function.coordinate_system`` to ``orientation.reference_frame``.

    Args:
        tf (TF): The transfer function, modified in place.

    Returns:
        str: The frame, e.g. "geomagnetic".
    """
    frame = _text(tf.station_metadata.orientation.reference_frame)
    tf.station_metadata.transfer_function.coordinate_system = frame
    return frame


def has_declination(station_metadata) -> bool:
    """Whether a station carries a declination.

    The value with an epoch, or a non-zero value. An archive built before
    the survey.yaml key existed carries mt_metadata's default, 0.0 with no
    epoch, which counts as unset.
    """
    d = station_metadata.location.declination
    return d.value is not None and (d.epoch is not None or float(d.value) != 0.0)


def zrot_rule_of(survey) -> str:
    """Return a survey's ZROT rule: its survey.yaml `products: {zrot: ...}`, "declination" without the block.

    Args:
        survey: A `mt_workbench.survey.Survey` (its ``config``).

    Returns:
        str: "declination" or "zero".

    Raises:
        ValueError: For any other value.
    """
    block = (getattr(survey, "config", None) or {}).get("products") or {}
    rule = str(block.get("zrot", "declination")).strip().lower()
    if rule not in ZROT_RULES:
        raise ValueError(f"survey.yaml products zrot {block.get('zrot')!r}: one of {', '.join(ZROT_RULES)}")
    return rule


def set_zrot_rule(tf, rule: str) -> None:
    """Record a TF's ZROT rule in its processing parameters (`ZROT_KEY`).

    "zero" adds the line ``mt_workbench.zrot_rule=zero ...``, which
    `edi_azimuth` reads and the EDI carries (so a product made from it, a
    merge, keeps the rule); "declination" (the default) removes any such line
    and adds none, so a product is written as before this option existed.

    Args:
        tf (TF): The transfer function.
        rule (str): "declination" or "zero".
    """
    if rule not in ZROT_RULES:
        raise ValueError(f"zrot rule {rule!r}: one of {', '.join(ZROT_RULES)}")
    params = tf.station_metadata.transfer_function
    kept = [x for x in (params.processing_parameters or []) if not _key_is(x, ZROT_KEY)]
    if rule == "zero":
        kept.append(f"{ZROT_KEY}=zero (survey.yaml products.zrot: ZROT and TROT 0, the declination recorded only)")
    params.processing_parameters = kept


def tf_zrot_rule(tf) -> str:
    """Return the ZROT rule a TF's processing parameters record (`set_zrot_rule`), "declination" without one.

    Read from the line as written (``mt_workbench.zrot_rule=``) and as
    mt_metadata's EDI reader gives it back (``zrot_rule=``).
    """
    for line in tf.station_metadata.transfer_function.processing_parameters or []:
        if _key_is(line, ZROT_KEY):
            value = str(line).partition("=")[2].strip().split(" ", 1)[0].lower()
            if value in ZROT_RULES:
                return value
    return "declination"


def _key_is(line, key: str) -> bool:
    """Whether a processing-parameter line's key is `key` (``mt_workbench.x``), as written or read back (``x``)."""
    k = str(line).split("=", 1)[0].strip()
    bare = key.split(".", 1)[1] if key.startswith("mt_workbench.") else key
    return k == key or k == bare or k.endswith("." + key) or k.endswith("." + bare)


def edi_azimuth(tf) -> float:
    """Return what a TF's EDI writes as ZROT and TROT: `x_azimuth`, or 0 under the zero rule (`tf_zrot_rule`)."""
    return 0.0 if tf_zrot_rule(tf) == "zero" else x_azimuth(tf)


def x_azimuth(tf) -> float:
    """Return the azimuth of a TF's x-axis, degrees clockwise from geographic north.

    The declination when the frame is geomagnetic and the declination is
    set (`has_declination`); 0.0 otherwise (a geographic layout, or an
    unset declination). The EDI writes it as ZROT and TROT and the XML as
    angle_to_geographic_north.

    Args:
        tf (TF): The transfer function.

    Returns:
        float: The azimuth in degrees, east positive.
    """
    sm = tf.station_metadata
    if _text(sm.orientation.reference_frame) == "geomagnetic" and has_declination(sm):
        return float(sm.location.declination.value)
    return 0.0


def _safe(text) -> str:
    """Return text fit for an INFO value: no "|", no line break."""
    return str(text).replace("|", "/").replace("\r", " ").replace("\n", " ")


def tf_rot_h(tf) -> float | None:
    """Return the turn the archive's ingest gave the horizontal fluxgate pair of a TF's local site.

    Read from the TF's run comments, which aurora carries from the archive's
    run comments, where mt_workbench.ingest._rot_h writes "rot_h: <angle>
    deg applied at ingest, ..."; failing that from an ``mt_workbench.rot_h``
    processing parameter, which a TF read back from one of these products'
    EDIs carries (`frame_info_lines`).

    Args:
        tf (TF): The transfer function.

    Returns:
        float or None: The angle in degrees
        (mt_workbench.survey.SiteConfig.rot_h); None when neither records
        one: H on the sensor axes as recorded, or a product made before the
        key existed.
    """
    sm = tf.station_metadata
    for run in sm.runs or []:
        comment = run.comments
        text = str(getattr(comment, "value", comment) or "")
        for piece in text.split("; "):
            if piece.startswith(ROT_H_PREFIX):
                try:
                    return float(piece[len(ROT_H_PREFIX):].split(" ", 1)[0])
                except ValueError:
                    continue
    for line in sm.transfer_function.processing_parameters or []:
        key, _, value = str(line).partition("=")
        key = key.strip()
        # mt_metadata's EDI reader keeps the key after "processing_parameters.mt_workbench.": "rot_h"
        if key in ("rot_h", "mt_workbench.rot_h") or key.endswith(".mt_workbench.rot_h"):
            try:
                return float(value.strip().split(" ", 1)[0])
            except ValueError:
                continue
    return None


def tf_rot_h_parts(tf) -> list | None:
    """Return the per-part turns (`rot_h_parts`) the archive's ingest gave a TF's local site, sorted by start.

    Read from the TF's run comments ("rot_h_part: <angle> deg over <start> .. <end> ...", one per archive run that
    went into it), else from an ``mt_workbench.rot_h_parts`` processing parameter (a TF read back from one of these
    products' EDIs, `frame_info_lines`).

    Returns:
        list or None: [[start ISO, end ISO, angle], ...]; None when no part is recorded.
    """
    import re

    sm = tf.station_metadata
    found = []
    for run in sm.runs or []:
        comment = run.comments
        text = str(getattr(comment, "value", comment) or "")
        for piece in text.split("; "):
            part = parse_rot_h_part(piece)
            if part and part not in found:
                found.append(part)
    if not found:
        for line in sm.transfer_function.processing_parameters or []:
            key, _, value = str(line).partition("=")
            key = key.strip()
            if key in ("rot_h_parts", "mt_workbench.rot_h_parts") or key.endswith(".mt_workbench.rot_h_parts"):
                for a, s, e in re.findall(r"(-?[0-9.]+) deg (\d{8}T\d{6}Z)/(\d{8}T\d{6}Z)", value):
                    found.append(parse_rot_h_part(f"{ROT_H_PARTS_PREFIX}{a} deg over {s} .. {e}"))
    return sorted(found, key=lambda p: p[0]) or None


def tf_h_tilt(tf) -> list | None:
    """Return the attitude correction (`h_tilt`, a rotation vector in degrees) the archive's ingest gave a TF's local
    site's fluxgate, from the TF's run comments ("h_tilt: <rx> <ry> <rz> deg ..."), else from an ``mt_workbench.h_tilt``
    processing parameter (a TF read back from one of these products' EDIs, `frame_info_lines`); None when none."""
    sm = tf.station_metadata
    for run in sm.runs or []:
        comment = run.comments
        text = str(getattr(comment, "value", comment) or "")
        for piece in text.split("; "):
            vec = parse_h_tilt(piece)
            if vec:
                return vec
    for line in sm.transfer_function.processing_parameters or []:
        key, _, value = str(line).partition("=")
        key = key.strip()
        if key in ("h_tilt", "mt_workbench.h_tilt") or key.endswith(".mt_workbench.h_tilt"):
            vec = parse_h_tilt(f"{H_TILT_PREFIX}{value.strip()}")
            if vec:
                return vec
    return None


def frame_info_lines(tf) -> list[str]:
    """Build the ``mt_workbench.*`` INFO lines that state a TF's frame in words.

    Geotools drops the EDI's COORDINATE_SYSTEM and zeroes AZM but keeps INFO
    as written, so these lines carry the frame through it:
    ``mt_workbench.frame`` (the x-axis azimuth), ``mt_workbench.rotation``
    (the data are not rotated; what ZROT and TROT hold), when a
    declination is stored ``mt_workbench.declination``,
    ``mt_workbench.declination_model`` and ``mt_workbench.declination_epoch``,
    and when the local site's ingest turned its fluxgate pair onto magnetic
    north (`tf_rot_h`) ``mt_workbench.rot_h``.
    Each written line (``transfer_function.processing_parameters.`` plus
    the text) stays under INFO_MAX characters.

    Args:
        tf (TF): The transfer function.

    Returns:
        list[str]: The lines, ``key=value`` each.
    """
    sm = tf.station_metadata
    frame = _text(sm.orientation.reference_frame)
    d = sm.location.declination
    stored = has_declination(sm)
    zero = tf_zrot_rule(tf) == "zero"
    if frame == "geomagnetic" and stored and zero:
        az = x_azimuth(tf)
        lines = [f"mt_workbench.frame=geomagnetic: sensor frame, x-axis along magnetic north (azimuth {az:.2f} deg "
                 f"from geographic north)",
                 "mt_workbench.rotation=data not rotated; ZROT and TROT 0 (geomagnetic), the declination below not applied"]
    elif frame == "geomagnetic" and stored:
        az = x_azimuth(tf)
        lines = [f"mt_workbench.frame=sensor frame, x-axis at azimuth {az:.2f} deg clockwise from geographic north",
                 "mt_workbench.rotation=data not rotated; ZROT and TROT state this azimuth, the declination below"]
    elif frame == "geomagnetic":
        lines = ["mt_workbench.frame=sensor frame, x-axis along magnetic north at recording; no declination stored",
                 "mt_workbench.rotation=data not rotated; ZROT and TROT 0 (the declination is unknown)"]
    elif frame == "geographic":
        lines = ["mt_workbench.frame=sensors laid out to geographic north, x-axis at azimuth 0",
                 "mt_workbench.rotation=data not rotated; ZROT and TROT 0"]
    else:
        lines = [f"mt_workbench.frame={_safe(frame)}", "mt_workbench.rotation=data not rotated; ZROT and TROT 0"]
    if stored:
        lines += [f"mt_workbench.declination={float(d.value):.2f}",
                  f"mt_workbench.declination_model={_safe(d.model or 'unknown')}",
                  f"mt_workbench.declination_epoch={_safe(d.epoch or 'unknown')}"]
    turn = tf_rot_h(tf)
    if turn is not None:
        lines.append(f"mt_workbench.rot_h={turn!r} deg, hx and hy turned at ingest from the fluxgate axes onto "
                     f"magnetic north")
    parts = tf_rot_h_parts(tf)
    if parts:
        compact = lambda s: s.replace("-", "").replace(":", "")  # noqa: E731
        lines.append("mt_workbench.rot_h_parts=" + ", ".join(f"{a!r} deg {compact(s)}/{compact(e)}" for s, e, a in parts))
    tilt = tf_h_tilt(tf)
    if tilt:
        lines.append("mt_workbench.h_tilt=" + " ".join(repr(v) for v in tilt) + " deg rotation vector (sensor axes), "
                     "hx hy hz levelled at ingest")
    if zero:
        lines.append(f"{ZROT_KEY}=zero (survey.yaml products.zrot: ZROT and TROT 0, the declination recorded only)")
    for line in lines:
        if len(INFO_PREFIX + line) >= INFO_MAX:
            logger.warning(f"INFO line of {len(INFO_PREFIX + line)} characters: {line}")
    return lines


def _is_frame_line(line) -> bool:
    """Whether a processing-parameter line is one of `frame_info_lines`' keys."""
    return any(_key_is(line, k) for k in FRAME_INFO_KEYS)


def frame_record(tf, source: str | None = None) -> dict:
    """Return a TF's frame metadata for a sidecar.

    Args:
        tf (TF): The transfer function.
        source (str, optional): Where the declination came from, e.g.
            "survey.yaml", "archive" or the first source's EDI.

    Returns:
        dict: ``reference_frame``, ``coordinate_system``, ``declination``,
        ``declination_model``, ``declination_epoch``, ``declination_source``,
        ``zrot`` (the EDI's ZROT and TROT, `edi_azimuth`), ``zrot_rule``
        (`tf_zrot_rule`: "declination", where ZROT is also the XML's
        angle, or "zero"),
        ``rotated`` (always False: products are never rotated) and ``rot_h``
        (`tf_rot_h`: the turn of the local site's fluxgate pair onto
        magnetic north at ingest, a correction of the sensor's frame
        before any estimate; None when none is recorded). The four
        declination keys are None when no declination is stored
        (`has_declination`): mt_metadata's defaults, 0.0 and "IGRF" with no
        epoch, are not a measured value.
    """
    sm = tf.station_metadata
    d = sm.location.declination
    stored = has_declination(sm)
    return {"reference_frame": _text(sm.orientation.reference_frame),
            "coordinate_system": _text(sm.transfer_function.coordinate_system),
            "declination": float(d.value) if stored else None, "declination_model": d.model if stored else None,
            "declination_epoch": d.epoch if stored else None, "declination_source": source if stored else None,
            "zrot": edi_azimuth(tf), "zrot_rule": tf_zrot_rule(tf), "rotated": False, "rot_h": tf_rot_h(tf),
            "rot_h_parts": tf_rot_h_parts(tf), "h_tilt": tf_h_tilt(tf)}


def frame_gaps(tf) -> list[str]:
    """List what a TF read back from an EDI lacks in its frame metadata.

    An EDI written before mt_metadata's azimuth and declination fixes
    (fork commit 405e7ff) reads back with no declination and
    with hy at hx's azimuth (AZM=0.00 on every channel line).

    Args:
        tf (TF): The transfer function.

    Returns:
        list[str]: "no declination" and/or "hy azimuth equals hx azimuth
        (<deg> deg)"; empty when neither applies.
    """
    sm = tf.station_metadata
    d = sm.location.declination
    gaps = [] if (d.epoch is not None or d.value) else ["no declination"]
    if sm.runs:
        az = {ch.component: ch.measurement_azimuth for ch in sm.runs[0].channels}
        if "hx" in az and "hy" in az and az["hx"] == az["hy"]:
            gaps.append(f"hy azimuth equals hx azimuth ({float(az['hx']):g} deg)")
    return gaps


def keep_periods(tf, keep) -> None:
    """Keep only the periods of a TF where `keep` is True, in place.

    Args:
        tf (TF): The transfer function, modified in place.
        keep (array of bool): One value per period of ``tf.period``.
    """
    tf._transfer_function = tf._transfer_function.isel(period=np.flatnonzero(np.asarray(keep, dtype=bool)))


def bad_error_rows(tf) -> dict[str, np.ndarray]:
    """Find, for each output row of Z and T, the periods where the row must not be written.

    An element counts as estimated when its value is finite at some period;
    a row is marked at a period where one of its estimated elements has a
    non-finite value, or an error that is zero or not finite. An inversion
    would take a zero error as an exact datum. A row that is NaN at every
    period (an output aurora was not asked for) is never marked; a row
    that is NaN at a period where it is estimated elsewhere (a band its
    run did not keep, after `merge_rows` in process_rr.py) is marked there.

    Args:
        tf (TF): The transfer function.

    Returns:
        dict: Output channel name (the TF's nomenclature) to an array of
        bool, one value per period, for each estimated row of Z and T.
    """
    rows: dict[str, np.ndarray] = {}
    for values, errors in ((tf.impedance, tf.impedance_error), (tf.tipper, tf.tipper_error)):
        if values is None or errors is None:
            continue
        for name in values.coords["output"].values:
            v = np.asarray(values.sel(output=name).data)
            e = np.asarray(errors.sel(output=name).data, dtype=float)
            estimated = np.isfinite(v).any(axis=0)
            if not estimated.any():
                continue
            flag = estimated & (~np.isfinite(v) | ~np.isfinite(e) | (e <= 0.0))
            rows[str(name)] = flag.any(axis=1)
    return rows


def bad_error_periods(tf) -> np.ndarray:
    """Find the periods where every estimated row of Z and T is marked by `bad_error_rows`.

    Args:
        tf (TF): The transfer function.

    Returns:
        array of bool: One value per period, True where no row is left to
        write.
    """
    rows = bad_error_rows(tf)
    if not rows:
        return np.zeros(np.asarray(tf.period).size, dtype=bool)
    return np.logical_and.reduce(list(rows.values()))


def drop_bad_errors(tf, label: str) -> list[float]:
    """Blank the rows `bad_error_rows` marks and remove the periods left with no row, with warnings.

    A marked row is written as not estimated at that period: its value and
    error, and its row and column of the residual covariance, become NaN;
    the other rows keep their values. A period where every estimated row is
    marked is removed. A single aurora run with a zero error on every row
    (a band of one STFT window) therefore loses the period, while a merged
    TF (`merge_rows`) keeps each row's own periods.

    Args:
        tf (TF): The transfer function, modified in place.
        label (str): Start of the warning, e.g. the station name.

    Returns:
        list of float: The periods removed, in s.
    """
    rows = bad_error_rows(tf)
    period = np.asarray(tf.period, dtype=float)
    ds = tf._transfer_function
    blanked = []
    for name, flag in rows.items():
        if not flag.any():
            continue
        at = period[flag]
        sel = dict(period=ds["period"].values[flag], output=name)
        # a row already NaN there (a band its run did not keep) is not reported
        held = np.isfinite(np.asarray(ds["transfer_function"].loc[sel].data)).any(axis=-1)
        blanked += [(name, p) for p in at[held]]
        for var in ("transfer_function", "transfer_function_error"):
            ds[var].loc[sel] = np.nan
        ds["residual_covariance"].loc[sel] = np.nan
        ds["residual_covariance"].loc[dict(period=sel["period"], input=name)] = np.nan
    bad = bad_error_periods(tf)
    periods = [float(p) for p in period[bad]]
    if bad.any():
        keep_periods(tf, ~bad)
    # the rows blanked at a period that is kept (a removed period is reported below)
    blanked = [(name, p) for name, p in blanked if p not in periods]
    if blanked:
        logger.warning(f"{label}: rows with a zero or non-finite Z or T error written as not estimated: "
                       + ", ".join(f"{name} at {p:.4g} s" for name, p in blanked))
    if periods:
        logger.warning(f"{label}: {len(periods)} period(s) with no row left to write not written: "
                       + ", ".join(f"{p:.4g}" for p in periods) + " s")
    return periods


def has_covariance(tf) -> bool:
    """Whether a TF carries the residual and inverse signal covariances the XML writer writes."""
    try:
        return bool(tf.has_residual_covariance() and tf.has_inverse_signal_power())
    except Exception:  # an mt_metadata without the checks
        return False


def unestimated_cross(tf) -> int:
    """Count the periods whose residual Ex-Ey cross term is not estimated.

    aurora regresses each output channel separately and leaves the cross
    term NaN or 0; an estimate is never exactly 0.

    Args:
        tf (TF): The transfer function.

    Returns:
        int: Periods where the Ex-Ey or Ey-Ex term is NaN or 0; 0 when the
        TF carries no residual covariance.
    """
    if not has_covariance(tf):
        return 0
    ex, ey = tf.ex_ey
    rc = tf.residual_covariance
    bad = np.zeros(np.asarray(tf.period).size, dtype=bool)
    for out, inp in ((ex, ey), (ey, ex)):
        v = np.asarray(rc.loc[dict(output=out, input=inp)].data)
        bad |= ~np.isfinite(v) | (v == 0)
    return int(np.count_nonzero(bad))


def fill_residcov_cross(path: str | Path) -> int:
    """Write the Ex-Ey residual cross terms of an EMTF XML as 0 where the writer put the EMPTY fill.

    Inside each Z.RESIDCOV block, an Ex-Ey or Ey-Ex value of 1e32 (the
    writer's fill for a zero or NaN) becomes ``0.000000e+00 0.000000e+00``;
    the diagonal and everything outside the blocks are kept unchanged.

    Args:
        path (str or Path): The XML, rewritten in place.

    Returns:
        int: The values replaced.
    """
    path = Path(path)
    with open(path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    count = 0

    def cross(m: re.Match) -> str:
        nonlocal count
        if m.group(2) == m.group(3):
            return m.group(0)
        count += 1
        return f"{m.group(1)}0.000000e+00 0.000000e+00{m.group(4)}"

    new = _RESIDCOV.sub(lambda block: _EMPTY_CROSS.sub(cross, block.group(0)), text)
    if count:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(new)
    return count


def pid_info_lines(role: str, entry: dict | None) -> list[str]:
    """Build the INFO lines of one role's instrument registry DOIs, one line per instrument.

    Args:
        role (str): The role in the product: "local", "remote", or a merge
            source's "src<k>_local" / "src<k>_remote".
        entry (dict or None): ``{"site", "pids": {instrument: doi}}``, or
            for a stacked remote ``{"site", "members": {site: {instrument:
            doi}}}`` (scripts/process_rr.py's `instrument_pids_of`); None
            or empty gives no line.

    Returns:
        list of str: ``mt_workbench.instrument_pid_<role>_<instrument>=<doi>``;
        for the k-th member of a stack (from 1)
        ``mt_workbench.instrument_pid_<role>_m<k>_<instrument>=<doi> (<site>)``:
        the site goes in the value, since mt_metadata's EDI reader gives
        the keys back in lower case.
    """
    lines = []
    for instrument, doi in ((entry or {}).get("pids") or {}).items():
        lines.append(f"mt_workbench.{PID_INFO_KEY}{role}_{instrument}={_safe(doi)}")
    for k, (member, pids) in enumerate(((entry or {}).get("members") or {}).items(), start=1):
        for instrument, doi in (pids or {}).items():
            lines.append(f"mt_workbench.{PID_INFO_KEY}{role}_m{k}_{instrument}={_safe(doi)} ({_safe(member)})")
    for line in lines:
        if len(INFO_PREFIX + line) >= INFO_MAX:
            logger.warning(f"INFO line of {len(INFO_PREFIX + line)} characters: {line}")
    return lines


def tf_instrument_pids(tf) -> dict[str, str]:
    """Return the instrument registry DOIs a TF's processing parameters carry (`pid_info_lines`).

    Read from lines as written (``mt_workbench.instrument_pid_<path>=``) and
    as mt_metadata's EDI reader gives them back (``instrument_pid_<path>=``).

    Args:
        tf (TF): The transfer function.

    Returns:
        dict: Path ("local_logger", "remote_m1_logger",
        "src2_remote_logger"; lower case when read back from an EDI) to the
        value as written (the DOI or "none", a stack member's followed by
        its site in parentheses), in the order of the lines; the first of
        a repeated path kept. Empty when there is none.
    """
    out: dict[str, str] = {}
    for line in tf.station_metadata.transfer_function.processing_parameters or []:
        key, sep, value = str(line).partition("=")
        key = key.strip()
        if not sep or PID_INFO_KEY not in key:
            continue
        path = key[key.index(PID_INFO_KEY) + len(PID_INFO_KEY):]
        if path and path not in out:
            out[path] = value.strip()
    return out


def _pid_words(path: str, value: str) -> str:
    """Return one instrument registry DOI in words: "source 2 remote logger https://doi.org/10.82388/x".

    A stack member's path ("remote_m1_logger") and value ("10.82388/x
    (Kal014)") read "remote stack member Kal014 logger https://doi.org/...".
    """
    found = re.match(r"^(\S+)(?: \((.+)\))?$", value.strip())
    doi, member = (found.group(1), found.group(2)) if found else (value.strip(), None)
    link = "not in the registry" if doi.lower() == "none" else DOI_RESOLVER + doi
    instrument = next((i for i in PID_INSTRUMENTS if path == i or path.endswith("_" + i)), None)
    if instrument is None:
        return f"{path.replace('_', ' ')} {link}"
    prefix = path[:-len(instrument)].rstrip("_")
    m = re.match(r"^(?:src(\d+)_)?(local|remote)(?:_m\d+)?$", prefix)
    if m:
        words = ([f"source {m.group(1)}"] if m.group(1) else []) + [m.group(2)]
    else:
        words = [prefix.replace("_", " ")] if prefix else []
    if member:
        words.append(f"stack member {member}")
    return " ".join(words + [instrument.replace("_", " "), link])


def pid_sentence(tf) -> str | None:
    """Build the XML Notes' sentence naming a TF's instrument registry DOIs as links.

    Args:
        tf (TF): The transfer function; its `tf_instrument_pids`.

    Returns:
        str or None: "Instruments (AuScope instrument registry, PIDINST):
        local logger https://doi.org/10.82388/25jrcc6q; remote logger ...";
        an instrument declared none reads "not in the registry". None when
        the TF carries no DOI.
    """
    pids = tf_instrument_pids(tf)
    if not pids:
        return None
    parts = [_pid_words(path, value) for path, value in pids.items()]
    return f"Instruments (AuScope instrument registry, PIDINST): {'; '.join(parts)}."


def frame_note(tf, covariance: bool | None = None) -> str:
    """Build the XML's Notes text: the frame, the convention, the declination and the covariance carried.

    When the TF's INFO lines carry instrument registry DOIs, their
    sentence (`pid_sentence`) ends the paragraph.

    Args:
        tf (TF): The transfer function.
        covariance (bool, optional): Whether the residual and inverse signal
            covariances are written; `has_covariance` when None.

    Returns:
        str: One paragraph.
    """
    sm = tf.station_metadata
    frame = _text(sm.orientation.reference_frame)
    d = sm.location.declination
    stored = has_declination(sm)
    decl = (f"declination {float(d.value):+.2f} deg east of geographic north ({d.model or 'model unknown'}, "
            f"epoch {d.epoch or 'unknown'}; the Site Location Declination element carries the value and the whole "
            f"year only)") if stored else "no declination stored"
    if frame == "geomagnetic" and stored and tf_zrot_rule(tf) == "zero":
        az = x_azimuth(tf)
        head = (f"Frame: geomagnetic, the sensor frame as laid out to magnetic north, never rotated at processing. "
                f"The x-axis is magnetic north, at azimuth {az:.2f} deg east of geographic north, the declination "
                f"({d.model or 'model unknown'}, epoch {d.epoch or 'unknown'}), recorded and not applied. By the "
                f"survey's products.zrot zero (the Queensland convention) the EDI's ZROT and TROT are 0 and its "
                f"COORDINATE_SYSTEM geomagnetic; Site Orientation angle_to_geographic_north and the channel "
                f"orientations here state the azimuth (Hx {az:.2f}, Hy {90.0 + az:.2f})")
    elif frame == "geomagnetic" and stored:
        az = x_azimuth(tf)
        head = (f"Frame: geomagnetic, the sensor frame as laid out to magnetic north, never rotated at processing. "
                f"The x-axis is at azimuth {az:.2f} deg east of geographic north (positive clockwise), the "
                f"declination ({d.model or 'model unknown'}, epoch {d.epoch or 'unknown'}; the Site Location "
                f"Declination element carries the value and the whole year only). "
                f"Site Orientation angle_to_geographic_north and the channel orientations state it (Hx {az:.2f}, "
                f"Hy {90.0 + az:.2f}); this matches the convention Geotools writes for ZROT, and the EDI's ZROT and TROT carry "
                f"the same number with the data unrotated")
    elif frame == "geomagnetic":
        head = ("Frame: geomagnetic, the sensor frame as laid out to magnetic north, never rotated at processing; "
                "no declination stored, so Site Orientation angle_to_geographic_north is written 0 and the EDI's "
                "ZROT is 0 although the x-axis is magnetic north")
    elif frame == "geographic":
        head = (f"Frame: geographic, the sensors laid out to geographic north, never rotated at processing; x-axis "
                f"at azimuth 0 (angle_to_geographic_north 0, the EDI's ZROT 0); {decl}")
    else:
        head = f"Frame: {frame}, never rotated at processing; {decl}"
    if covariance is None:
        covariance = has_covariance(tf)
    cov = ("RESIDCOV and INVSIGCOV are carried: the full error covariance for a rotation."
           if covariance else
           "No RESIDCOV or INVSIGCOV: the errors are per-component variances only (a product built from EDIs, "
           "or by an engine that gives none).")
    cross = f" {CROSS_NOTE}" if covariance and unestimated_cross(tf) else ""
    pids = pid_sentence(tf)  # the instruments' registry DOIs, when the TF's INFO lines carry them
    return f"{head}. {cov}{cross}" + (f" {pids}" if pids else "")


def archive_geometry(path: str | Path, station: str | None = None) -> dict[str, dict]:
    """Read each channel's geometry from an archive, from the first run of the station.

    Args:
        path (str or Path): The MTH5 archive.
        station (str, optional): The station; the archive's first when None.

    Returns:
        dict: Channel to ``azimuth`` (measurement azimuth, deg), ``tilt``
        (measurement tilt, deg; 90 for an hz the archive gives none) and,
        for an electric channel, ``dipole_length`` (m), ``negative`` (x, y)
        and ``positive`` (x2, y2) in m: the archive's electrode positions,
        or, where they are all zero, the centre and the length along the
        azimuth.

    Raises:
        ValueError: When the archive holds no run with channels.
    """
    import h5py

    out: dict[str, dict] = {}
    with h5py.File(path, "r") as f:
        surveys = f["Experiment/Surveys"]
        sv = surveys[list(surveys.keys())[0]]
        stations = sv["Stations"]
        st = stations[station] if station else stations[list(stations.keys())[0]]
        runs = [k for k in st.keys() if hasattr(st[k], "keys") and any(
            str(st[k][c].attrs.get("mth5_type", "")).lower() in ("electric", "magnetic") for c in st[k].keys())]
        if not runs:
            raise ValueError(f"{path}: no run with channels")
        run = st[sorted(runs)[0]]
        for ch in run.keys():
            a = run[ch].attrs
            comp = str(a.get("component", ch)).lower()
            g = {"azimuth": float(a.get("measurement_azimuth", 0.0) or 0.0),
                 "tilt": float(a.get("measurement_tilt", 0.0) or 0.0)}
            if comp.startswith("e"):
                length = float(a.get("dipole_length", 0.0) or 0.0)
                neg = (float(a.get("negative.x", 0.0) or 0.0), float(a.get("negative.y", 0.0) or 0.0))
                pos = (float(a.get("positive.x2", 0.0) or 0.0), float(a.get("positive.y2", 0.0) or 0.0))
                if not any(neg + pos) and length > 0:
                    rad = np.radians(g["azimuth"])
                    neg, pos = (0.0, 0.0), (float(round(length * np.cos(rad), 6)) + 0.0,
                                            float(round(length * np.sin(rad), 6)) + 0.0)
                g.update({"dipole_length": length, "negative": neg, "positive": pos})
            elif comp == "hz" and not g["tilt"]:
                g["tilt"] = 90.0
            out[comp] = g
    return out


def set_channel_geometry(tf, geometry: dict[str, dict]) -> list[str]:
    """Write channel geometry (`archive_geometry`'s form) into every run of a TF's station metadata, in place.

    Each named channel gets its measurement azimuth (and no translated
    azimuth, which the EDI writer would take before it) and tilt; an
    electric channel its dipole length and electrode positions.

    Args:
        tf (TF): The transfer function, changed in place.
        geometry (dict): Channel to its geometry.

    Returns:
        list of str: "<run> <channel>" for each channel set.
    """
    done = []
    for run in tf.station_metadata.runs:
        for ch in run.channels:
            g = geometry.get(str(ch.component).lower()) if ch.component else None
            if g is None:
                continue
            ch.measurement_azimuth = g["azimuth"]
            ch.translated_azimuth = None
            if g.get("tilt") is not None and hasattr(ch, "measurement_tilt"):
                ch.measurement_tilt = g["tilt"]
            if "dipole_length" in g:
                ch.dipole_length = g["dipole_length"]
                ch.negative.x, ch.negative.y = g["negative"]
                ch.positive.x2, ch.positive.y2 = g["positive"]
            done.append(f"{run.id} {ch.component}")
    return done


def edi_copy(tf, geometry: dict[str, dict] | None = None):
    """Return the copy of a TF the EDI is written from.

    Its rotation angle is `edi_azimuth` (`x_azimuth`, or 0 under the
    survey's products.zrot zero; the EDI writer repeats it as ZROT
    at every period, and as TROT when a tipper is written); the data are
    not rotated. Its processing parameters get `frame_info_lines` in place
    of any frame lines it carried (a TF read back from an EDI). With
    `geometry` (`archive_geometry`), its channels carry that geometry, so
    the EMEAS and HMEAS lines state the azimuths and the dipoles.

    Args:
        tf (TF): The transfer function, left as it was.
        geometry (dict, optional): Channel geometry; None keeps the TF's.

    Returns:
        TF: The copy.
    """
    tfc = copy.deepcopy(tf)
    if geometry:
        set_channel_geometry(tfc, geometry)
    tfc._rotation_angle = edi_azimuth(tfc)  # mt_metadata holds the ZROT of a TF here; there is no setter
    params = tfc.station_metadata.transfer_function
    kept = [p for p in (params.processing_parameters or []) if not _is_frame_line(p)]
    params.processing_parameters = kept + frame_info_lines(tfc)
    return tfc


def dot_free_comment_keys(text: str) -> str:
    """Return a run comment with the dots of its "key: value" keys replaced by underscores.

    mt_metadata's EMTF XML writer splits a run comment on ";", takes the
    text before the first ":" of each piece as an attribute path and
    raises when it cannot set it, so a key with a dot stops the write
    (upstream issues 48 and 82: "dc rail (V, 0.9 x the input range)", the
    run-comment key of the Phoenix archives built from 4beb3cd until 8 Oct
    2026). Pieces without a ":" and every value are kept as they are.

    Args:
        text (str): The run comment.

    Returns:
        str: The comment with each piece's key free of dots, e.g. "dc rail
        (V, 0_9 x the input range): ex 2.25".
    """
    pieces = []
    for piece in text.split(";"):
        key, sep, value = piece.partition(":")
        if sep and "." in key:
            key = key.replace(".", "_")
        pieces.append(key + sep + value)
    return ";".join(pieces)


def admissible_run_id(text: str) -> str:
    """Return a run id with each character mt_metadata's Run id pattern refuses replaced by "_".

    Args:
        text (str): The run id, e.g. the placeholder "KD-Q5a".

    Returns:
        str: The id matching ``^[a-zA-Z0-9_]*$``, e.g. "KD_Q5a".
    """
    return _RUN_ID_REFUSED.sub("_", text)


@contextmanager
def hyphenated_station_ids():
    """Let mt_metadata write and read an EDI or EMTF XML whose station id holds a hyphen.

    mt_metadata 1.0.10 admits a hyphen in a Station id
    (``^[a-zA-Z0-9_-]*$``) and not in a Run id (``^[a-zA-Z0-9_]*$``).
    Its EDI code (``EDI.station_metadata``, which the writer and the
    reader both call) and its EMTF XML reader (``EMTFXML.station_metadata``
    when the FieldNotes give no run) build a placeholder run
    ``Run(id=f"{station}a")``, so a station "KD-Q5" stops the EDI write and
    the XML read with a ValidationError (upstream issue 86; every Kalkaroo
    KD- site). Its EDI header reader also passes DATAID through
    ``validate_station_name``, which turns "KD-Q5" into "KD_Q5".

    Inside this context the name ``Run`` in those two modules gives
    mt_metadata's Run with the id passed through `admissible_run_id`
    ("KD_Q5a"), and the EDI reader's ``validate_station_name`` keeps the
    hyphens of the name (its other mappings and its refusals are kept).
    Run ids read from an EDI's INFO runlist pass through the same map.
    The station id, the EDI's DATAID, the XML's Site Id and the data are
    not changed; a station id without a hyphen is handled as before. The
    names are restored on exit. They are module globals, so the context
    is not for concurrent threads.

    Yields:
        None
    """
    from mt_metadata.timeseries import Run
    from mt_metadata.transfer_functions.io.edi import edi as edi_module
    from mt_metadata.transfer_functions.io.edi.metadata import header as header_module
    from mt_metadata.transfer_functions.io.emtfxml import emtfxml as xml_module

    def admissible_run(*args, **kwargs):
        if isinstance(kwargs.get("id"), str):
            kwargs["id"] = admissible_run_id(kwargs["id"])
        return Run(*args, **kwargs)

    validate = header_module.validate_station_name

    def station_name_with_hyphens(name):
        checked = validate(name)  # mt_metadata's refusals stand
        kept = str(name).strip()
        for char in " .+":
            kept = kept.replace(char, "_")
        return kept if kept.replace("-", "_") == checked else checked

    saved = [(edi_module, "Run", edi_module.Run), (xml_module, "Run", xml_module.Run),
             (edi_module, "validate_station_name", edi_module.validate_station_name),
             (header_module, "validate_station_name", header_module.validate_station_name)]
    edi_module.Run = xml_module.Run = admissible_run
    edi_module.validate_station_name = header_module.validate_station_name = station_name_with_hyphens
    try:
        yield
    finally:
        for module, name, value in saved:
            setattr(module, name, value)


def read_tf(path: str | Path):
    """Read a transfer-function file (EDI, EMTF XML, ...) into an mt_metadata TF.

    Read inside `hyphenated_station_ids`, so a station id with a hyphen
    reads back as written (KD-Q5, not KD_Q5, and no ValidationError).

    Args:
        path (str or Path): The file.

    Returns:
        TF: The transfer function.
    """
    from mt_metadata.transfer_functions.core import TF

    with hyphenated_station_ids():
        tf = TF(fn=str(path))
        tf.read()
    return tf


def xml_copy(tf):
    """Return the copy of a TF the EMTF XML is written from.

    It keeps only the channels the TF holds data for: mt_metadata's XML
    writer builds its site layout from every channel of the runs and then
    looks each layout channel up in every run, failing on a run without it,
    and an aurora TF's station metadata can list hz in one run and not in
    another while the TF has no tipper. Each run's comment is passed
    through `dot_free_comment_keys`, since the writer takes the keys of
    its "key: value" pieces as attribute paths. For a geomagnetic frame with the
    declination set, Site Orientation angle_to_geographic_north is the
    declination and each horizontal channel's ``translated_azimuth`` (the
    orientation the writer gives it) is its measurement azimuth plus the
    declination; the data are not rotated.

    Args:
        tf (TF): The transfer function, left as it was.

    Returns:
        TF: The copy.
    """
    tfc = copy.deepcopy(tf)
    names = dict(getattr(tfc, "channel_nomenclature", None) or {})
    held = {names.get(c, c) for c in ("ex", "ey", "hx", "hy")}
    if tfc.has_tipper():
        held.add(names.get("hz", "hz"))
    for run in tfc.station_metadata.runs:
        for ch in list(run.channels):
            if ch.component not in held:
                run.remove_channel(ch.component)
        comments = run.comments
        if hasattr(comments, "value"):
            if comments.value:
                comments.value = dot_free_comment_keys(str(comments.value))
        elif comments:
            run.comments = dot_free_comment_keys(str(comments))
    az = x_azimuth(tfc)
    sm = tfc.station_metadata
    if az != 0.0:
        sm.orientation.angle_to_geographic_north = az
        horizontal = {names.get(c, c) for c in HORIZONTAL}
        for run in sm.runs:
            for ch in run.channels:
                if ch.component in horizontal:
                    ch.translated_azimuth = float(ch.measurement_azimuth or 0.0) + az
    else:
        sm.orientation.angle_to_geographic_north = 0.0
    return tfc


def drop_declination_element(path: str | Path) -> int:
    """Remove the Site Location Declination element from a written EMTF XML.

    mt_metadata's writer (`Location.to_xml` of its emtfxml metadata) always
    writes the element, with the value and the epoch "1995" when none is
    set; it has no form for an unknown declination, and its reader takes a
    Location without the element as the default (0.0, no epoch).

    Args:
        path (str or Path): The .xml, rewritten in place.

    Returns:
        int: The number of elements removed.
    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    new, n = _DECLINATION.subn("", text)
    if n:
        path.write_text(new, encoding="utf-8", newline="")
    return n


def write_xml(tf, path: str | Path, note: str | None = None) -> Path:
    """Write a TF as EMTF XML with a Notes paragraph.

    Written from `xml_copy`, inside `hyphenated_station_ids`. Where the
    residual Ex-Ey cross term is not estimated (`unestimated_cross`), the
    written values are 0, not the
    writer's EMPTY fill (`fill_residcov_cross`). A TF with no declination
    stored (`has_declination`) is written with no Declination element
    (`drop_declination_element`), where the writer would put 0 at 1995.

    Args:
        tf (TF): The transfer function; a copy is written.
        path (str or Path): The .xml to write.
        note (str, optional): The Notes text; `frame_note` when None.

    Returns:
        Path: The file written.
    """
    path = Path(path)
    tfc = xml_copy(tf)
    note = frame_note(tfc) if note is None else note
    with hyphenated_station_ids():
        xml = tfc.write(fn=path, file_type="xml")
        xml.notes = note
        xml.write(path)
    if not has_declination(tfc.station_metadata):
        drop_declination_element(path)
    if unestimated_cross(tfc):
        n = fill_residcov_cross(path)
        logger.info(f"{path.name}: residual Ex-Ey cross term not estimated, written as 0 ({n} values)")
    return path


def write_h5(tf, path: str | Path) -> Path:
    """Write a TF into a new standalone MTH5 file.

    The file is created fresh (mode "w", file version 0.2.0) under a
    ``.part`` name and moved onto `path` once closed. It holds one survey,
    one station and the TF, with the TF's survey and station metadata. The
    TF's id is its own, or the station id when it has none (aurora leaves it
    empty; ``MTH5.tf_summary`` keeps 30 characters of an id, too few for a
    product stem); ``MTH5.tf_summary`` lists it and
    ``MTH5.get_transfer_function(station, tf_id, survey=...)`` reads it.
    A residual Ex-Ey cross term that is not estimated is written as 0, and
    the station comments say so (CROSS_NOTE).

    Args:
        tf (TF): The transfer function; a copy is written, since
            `MTH5.add_transfer_function` renames an unnamed survey.
        path (str or Path): The .h5 to write.

    Returns:
        Path: The file written.
    """
    from mth5.mth5 import MTH5

    path = Path(path)
    tmp = path.with_name(path.name + ".part")
    if tmp.exists():
        tmp.unlink()
    tfc = copy.deepcopy(tf)
    if not tfc.tf_id:  # aurora leaves it empty, and an MTH5 group needs a name
        # the station id, as an EDI read back gives: tf_summary keeps 30 characters of an id,
        # so a product stem would not look up
        tfc.tf_id = tfc.station_metadata.id or path.stem[:30]
    if unestimated_cross(tfc):
        rc = tfc.residual_covariance.copy()
        ex, ey = tfc.ex_ey
        for out, inp in ((ex, ey), (ey, ex)):
            sel = dict(output=out, input=inp)
            rc.loc[sel] = np.nan_to_num(np.asarray(rc.loc[sel].data))
        tfc.residual_covariance = rc
        comments = tfc.station_metadata.comments
        prior = comments.value
        comments.value = f"{prior}; {CROSS_NOTE}" if prior else CROSS_NOTE
    m = MTH5(file_version="0.2.0")
    m.open_mth5(tmp, mode="w")
    try:
        m.add_transfer_function(tfc)
    finally:
        m.close_mth5()
    os.replace(tmp, path)
    return path


def _instrument_row(survey, site: str) -> dict | None:
    """Return a site's row of <survey folder>/instruments.csv (its parent's for a derived site), None without one."""
    folder = getattr(survey, "folder", None) or getattr(survey, "config_dir", None)  # Survey: config_dir
    if folder is None:
        return None
    path = Path(folder) / INSTRUMENTS_CSV
    if not path.is_file():
        return None
    import csv

    with open(path, encoding="utf-8", newline="") as fh:
        rows = {str(r.get("site") or "").strip(): r for r in csv.DictReader(fh)}
    row = rows.get(site)
    if row is None:
        parent = survey.parent_of(site) if hasattr(survey, "parent_of") else None
        row = rows.get(parent) if parent else None
    return row


def _clean(value) -> str:
    """One instruments.csv cell as INFO text: stripped, single-spaced, "" for empty."""
    return " ".join(_safe(value or "").split())


def _fit(key: str, value: str, cut: bool = True) -> str:
    """Return ``key=value``, the value cut with "..." so the written line stays under INFO_MAX (uncut: cut False)."""
    if not cut:
        return f"{key}={value}"
    room = INFO_MAX - 1 - len(INFO_PREFIX) - len(key) - 1
    return f"{key}={value if len(value) <= room else value[:room - 3].rstrip() + '...'}"


def instrument_info_lines(survey, site: str, cut: bool = True) -> list[str]:
    """Build the INFO lines of a site's instrument identity from <survey folder>/instruments.csv.

    ``mt_workbench.instrument_logger=<logger_model> <logger_serial>
    <logger_doi> (<logger_doi_source>)`` and
    ``mt_workbench.instrument_magnetometer=<magnetometer_model>
    <magnetometer_serial>``, the filled cells only; a line with no cell
    filled is not written. The keys use an underscore, not a dot after
    ``instrument``: mt_metadata's EDI reader keeps only the last dotted part
    of a key (upstream 115), so ``instrument.logger`` would come back as
    ``logger``. A value is cut with "..." to keep the line under INFO_MAX
    (instruments.csv holds the whole text); ``cut=False`` gives the same
    lines uncut, which the sidecar keeps beside the written ones. A derived site (survey.yaml `derived_from`) takes its
    parent's row.

    Args:
        survey: The survey (its ``folder`` and ``parent_of``).
        site (str): The site.
        cut (bool): Cut each line to INFO_MAX (the INFO block); False for the whole text.

    Returns:
        list[str]: The lines; [] without the file or the site's row.
    """
    row = _instrument_row(survey, site)
    if not row:
        return []
    lines = []
    logger_text = " ".join(x for x in (_clean(row.get("logger_model")), _clean(row.get("logger_serial")),
                                       _clean(row.get("logger_doi"))) if x)
    source = _clean(row.get("logger_doi_source"))
    if logger_text:
        lines.append(_fit("mt_workbench.instrument_logger", logger_text + (f" ({source})" if source else ""), cut))
    mag = " ".join(x for x in (_clean(row.get("magnetometer_model")), _clean(row.get("magnetometer_serial"))) if x)
    if mag:
        lines.append(_fit("mt_workbench.instrument_magnetometer", mag, cut))
    return lines


def apply_instruments(tf, survey, site: str) -> bool:
    """Write a site's instruments.csv identity into a TF's station metadata, where mt_metadata has fields.

    Every run's ``data_logger.id`` (logger_serial) and ``data_logger.model``
    (logger_model); every magnetic channel's ``sensor.id``
    (magnetometer_serial) and ``sensor.model`` (magnetometer_model). Empty
    cells leave a field as it was.

    Returns:
        bool: True when the site has a row.
    """
    row = _instrument_row(survey, site)
    if not row:
        return False
    serial, model = _clean(row.get("logger_serial")), _clean(row.get("logger_model"))
    m_serial, m_model = _clean(row.get("magnetometer_serial")), _clean(row.get("magnetometer_model"))
    for run in tf.station_metadata.runs or []:
        if serial:
            run.data_logger.id = serial
        if model:
            run.data_logger.model = model
        for ch in run.channels or []:
            if str(getattr(ch, "component", "")).lower() in ("hx", "hy", "hz") and hasattr(ch, "sensor"):
                if m_serial:
                    ch.sensor.id = m_serial
                if m_model:
                    ch.sensor.model = m_model
    return True


def write_edi(tf, path: str | Path, geometry: dict[str, dict] | None = None) -> Path:
    """Write a TF as an EDI from `edi_copy` (with `geometry`, when given), inside `hyphenated_station_ids`.

    The TF is left as it was.
    """
    path = Path(path)
    with hyphenated_station_ids():
        edi_copy(tf, geometry).write(fn=path, file_type="edi")
    return path


def write_products(tf, edi_path: str | Path, note: str | None = None,
                   geometry: dict[str, dict] | None = None) -> dict[str, Path]:
    """Write a row's EDI, EMTF XML and standalone TF h5 under one stem.

    ``transfer_function.coordinate_system`` is first set to the reference
    frame (`match_coordinate_system`). The data are written as estimated.

    Args:
        tf (TF): The transfer function.
        edi_path (str or Path): The EDI; the .xml and .h5 go beside it.
        note (str, optional): The XML's Notes; `frame_note` when None.
        geometry (dict, optional): Channel geometry for the EDI's
            measurement lines (`archive_geometry`); None keeps the TF's.

    Returns:
        dict: ``{"edi": Path, "xml": Path, "h5": Path}``.
    """
    paths = product_paths(edi_path)
    paths["edi"].parent.mkdir(parents=True, exist_ok=True)
    match_coordinate_system(tf)
    write_edi(tf, paths["edi"], geometry)
    write_xml(tf, paths["xml"], note)
    write_h5(tf, paths["h5"])
    for path in paths.values():
        logger.info(f"wrote {path}")
    tf_index.add(paths["edi"])
    return paths
