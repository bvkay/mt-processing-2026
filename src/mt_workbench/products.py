# -*- coding: utf-8 -*-
"""
Transfer-function products: the frame metadata and the three files of a row

Every product is kept in the frame the sensors were laid out in and is
never rotated at processing. The survey says which north the sensors were
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
round-trips unchanged (export test, 2 Oct 2026); how Geotools treats a
non-zero ZROT on import is not yet tested. Geotools drops
COORDINATE_SYSTEM and zeroes AZM on export but keeps the INFO block, so
the frame is also stated in words there (`frame_info_lines`,
``mt_workbench.frame``, ``mt_workbench.rotation`` and the three
``mt_workbench.declination*`` lines). The EMTF XML states it in its own
fields (`xml_copy`): Site Orientation angle_to_geographic_north D and each
horizontal channel's orientation its measurement azimuth plus D (Hx D,
Hy 90 + D, Ex D, Ey 90 + D). A geographic layout, or a geomagnetic one
whose declination is unset, gives ZROT 0 and angle 0.

`write_products` writes a row's three files from one TF, under one stem:

* ``<stem>.edi`` (`edi_copy`: ZROT and the INFO frame lines);
* ``<stem>.xml``, the EMTF XML of mt_metadata's writer (`xml_copy`), whose
  Notes state the frame, the convention, the declination and whether the
  residual and inverse signal covariances (RESIDCOV, INVSIGCOV) are carried
  (`frame_note`);
* ``<stem>.h5``, a standalone MTH5 file created fresh, holding the survey and
  station metadata and this TF (`mth5.mth5.MTH5.add_transfer_function`),
  which `mth5.mth5.MTH5.get_transfer_function` reads back.

It then records the product in its folder's index from the sidecar beside
the EDI, when there is one (`mt_workbench.tf_index.add`; the View EDIs list
reads the index instead of every sidecar).

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
whose runs disagree on hz.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import copy
import os
import re
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
                   "mt_workbench.declination_model", "mt_workbench.declination_epoch")
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

    `set_reference_frame` then `apply_site_declination`; nothing is
    rotated.

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


def frame_info_lines(tf) -> list[str]:
    """Build the ``mt_workbench.*`` INFO lines that state a TF's frame in words.

    Geotools drops the EDI's COORDINATE_SYSTEM and zeroes AZM but keeps INFO
    as written, so these lines carry the frame through it:
    ``mt_workbench.frame`` (the x-axis azimuth), ``mt_workbench.rotation``
    (the data are not rotated; what ZROT and TROT hold) and, when a
    declination is stored, ``mt_workbench.declination``,
    ``mt_workbench.declination_model`` and ``mt_workbench.declination_epoch``.
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
    if frame == "geomagnetic" and stored:
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
    for line in lines:
        if len(INFO_PREFIX + line) >= INFO_MAX:
            logger.warning(f"INFO line of {len(INFO_PREFIX + line)} characters: {line}")
    return lines


def _is_frame_line(line) -> bool:
    """Whether a processing-parameter line is one of `frame_info_lines`' keys."""
    key = str(line).split("=", 1)[0].strip()
    return any(key == k or key.endswith("." + k) for k in FRAME_INFO_KEYS)


def frame_record(tf, source: str | None = None) -> dict:
    """Return a TF's frame metadata for a sidecar.

    Args:
        tf (TF): The transfer function.
        source (str, optional): Where the declination came from, e.g.
            "survey.yaml", "archive" or the first source's EDI.

    Returns:
        dict: ``reference_frame``, ``coordinate_system``, ``declination``,
        ``declination_model``, ``declination_epoch``, ``declination_source``,
        ``zrot`` (the EDI's ZROT and TROT and the XML's angle, `x_azimuth`)
        and ``rotated`` (always False: products are never rotated). The four
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
            "zrot": x_azimuth(tf), "rotated": False}


def frame_gaps(tf) -> list[str]:
    """List what a TF read back from an EDI lacks in its frame metadata.

    An EDI written before mt_metadata's azimuth and declination fixes
    (fork commit 405e7ff, 2 Oct 2026) reads back with no declination and
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
    the diagonal and everything outside the blocks are kept byte for byte.

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


def frame_note(tf, covariance: bool | None = None) -> str:
    """Build the XML's Notes text: the frame, the convention, the declination and the covariance carried.

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
    if frame == "geomagnetic" and stored:
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
    return f"{head}. {cov}{cross}"


def edi_copy(tf):
    """Return the copy of a TF the EDI is written from.

    Its rotation angle is `x_azimuth` (the EDI writer repeats it as ZROT
    at every period, and as TROT when a tipper is written); the data are
    not rotated. Its processing parameters get `frame_info_lines` in place
    of any frame lines it carried (a TF read back from an EDI).

    Args:
        tf (TF): The transfer function, left as it was.

    Returns:
        TF: The copy.
    """
    tfc = copy.deepcopy(tf)
    tfc._rotation_angle = x_azimuth(tfc)  # mt_metadata holds the ZROT of a TF here; there is no setter
    params = tfc.station_metadata.transfer_function
    kept = [p for p in (params.processing_parameters or []) if not _is_frame_line(p)]
    params.processing_parameters = kept + frame_info_lines(tfc)
    return tfc


def xml_copy(tf):
    """Return the copy of a TF the EMTF XML is written from.

    It keeps only the channels the TF holds data for: mt_metadata's XML
    writer builds its site layout from every channel of the runs and then
    looks each layout channel up in every run, failing on a run without it,
    and an aurora TF's station metadata can list hz in one run and not in
    another while the TF has no tipper. For a geomagnetic frame with the
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

    Written from `xml_copy`. Where the residual Ex-Ey cross term is not
    estimated (`unestimated_cross`), the written values are 0, not the
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


def write_edi(tf, path: str | Path) -> Path:
    """Write a TF as an EDI from `edi_copy`, leaving the TF as it was."""
    path = Path(path)
    edi_copy(tf).write(fn=path, file_type="edi")
    return path


def write_products(tf, edi_path: str | Path, note: str | None = None) -> dict[str, Path]:
    """Write a row's EDI, EMTF XML and standalone TF h5 under one stem.

    ``transfer_function.coordinate_system`` is first set to the reference
    frame (`match_coordinate_system`). Nothing is rotated.

    Args:
        tf (TF): The transfer function.
        edi_path (str or Path): The EDI; the .xml and .h5 go beside it.
        note (str, optional): The XML's Notes; `frame_note` when None.

    Returns:
        dict: ``{"edi": Path, "xml": Path, "h5": Path}``.
    """
    paths = product_paths(edi_path)
    paths["edi"].parent.mkdir(parents=True, exist_ok=True)
    match_coordinate_system(tf)
    write_edi(tf, paths["edi"])
    write_xml(tf, paths["xml"], note)
    write_h5(tf, paths["h5"])
    for path in paths.values():
        logger.info(f"wrote {path}")
    tf_index.add(paths["edi"])
    return paths
