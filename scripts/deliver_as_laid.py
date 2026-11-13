# -*- coding: utf-8 -*-
"""
Write a delivered EDI with each measured-reversed electric line as laid

The ingest negates a line declared reversed (survey.yaml `azimuth_ex: 180` or
`azimuth_ey: 270` under `flip_reversed_dipoles: true`), so every product,
stack, merge and score is in the corrected frame (ex along 0, ey along 90).
At delivery, and only there, this script undoes that correction for each
reversed line: the line's Z row is written as the field was measured on the
dipole as laid, and its EMEAS line states the azimuth as laid. The
--corrected mode writes the other delivered form, every row in the nominal
frame: no row negated, EMEAS AZM nominal, and
one INFO line per reversed line stating the reversal and its measurement.

For each line the site declares reversed:

* ex (azimuth_ex 180): Zxx and Zxy are negated (real and imaginary parts),
  ey (azimuth_ey 270): Zyx and Zyy. Nothing else changes: the errors (a
  sign does not change a variance), the other row, the tipper (H only), the
  periods and the rotation angles are written as read.
* The line's EMEAS line states AZM=180.00 (ex) or AZM=270.00 (ey). Where the
  line carries electrode positions (X, Y and X2, Y2 not all zero), the two
  ends are exchanged, so the positions state the as-laid direction too (the
  same two points; the negative end where the positive was). The other
  EMEAS line and the HMEAS lines keep the azimuth, tilt (DIP), electrode
  positions and ACQCHAN of the input.
* One INFO line per reversed line, ``mt_workbench.as_laid_ex`` or
  ``mt_workbench.as_laid_ey``, written as a processing parameter (the
  mechanism of merge_best's and the Run finalizers' ``mt_workbench.*``
  lines and flags), so it lands in the >INFO block as
  ``transfer_function.processing_parameters.mt_workbench.as_laid_ey=...``
  beside the delivered flags. Its text: "ey written as laid: AZM 270; the
  yx row (Zyx, Zyy) is the field as measured on the reversed dipole; a
  reader assuming north and east sees it 180 deg out, a reader honouring AZM
  recovers the tensor; reversal measured <date> (<fragment>), declared in
  survey.yaml; " followed by ``RULING``. The date and the fragment are quoted
  from the site's survey.yaml `notes:` (`measurement`): the clause holding
  "<Ex|Ey> declared reversed" (the name as a whole word; "ex+ey declared
  reversed" is the joint form and declares both lines) gives either the
  measurement after the declaration ("census VIC001 rr VIC006 xy -134.7
  deg (out; ...)", with the dated header that ``STAGE`` matches, taken
  from the clause or the nearest clause before it) or the one before it
  ("polarity measured 2026-11-02, yx 180 deg out as ingested"); with no
  such clause, or a joint clause with no text before or after it
  ("ex+ey declared reversed"),
  the line says "reversal declared in survey.yaml".
  The line is longer than products.INFO_MAX (160): the frame lines' limit,
  which the flag legend lines exceed too; mt_metadata reads it back
  whole.

The site is the EDI's DATAID unless --site names it; it must have its own
entry in survey.yaml's `sites:` (no declaration is read from `defaults:`).
A derived site (`derived_from:`) is read through its parent, whose ingest
made the correction its archive carries, and must declare the same
azimuths. Refused, with a message and no file written (exit 2): a site
with `swap_e: true` (the as-laid form of an exchanged pair is not built
here), an electric azimuth that is neither nominal nor reversed (a
rotation), a reversed azimuth under
`flip_reversed_dipoles: false` (the ingest made no correction to undo), a
reversed line without an EMEAS line in the EDI, an EDI already written as
laid (an ``mt_workbench.as_laid_*`` INFO line, or the reversed azimuth
already on the EMEAS line: the transform is applied once), and an output
path equal to the input. The written text is read back before it takes
the output's name: an EMEAS azimuth or an INFO line that is not what was
intended leaves it as ``<stem>_part.edi`` and delivers nothing (exit 2).
A site with no reversed line is written all the
same (the input re-written by the same writer, no INFO added, the record
saying "no reversed line; nothing transformed"), so a delivery loop can
call the script for every site.

The EDI is written as merge_best writes its merged EDI:
`mt_workbench.products.write_edi` (mt_metadata's TF writer through
`edi_copy`: ZROT and the INFO frame lines) and then merge_best's
`patch_edi_text` (LON and LONG, REFLON and REFLONG; the input's ACQBY and
PROSBY, when it has them, as the header block's acqby and prosby). What a
TF read back from an EDI would lose is taken from the input's text: the
processing-parameter lines (mt_metadata's reader drops the "mt_workbench."
of their keys), the measurement lines (mt_metadata's reader drops DIP, and
reads ACQCHAN 3.0 as 30, upstream 497), and the INFO lines
transfer_function.processed_date and provenance.software.*. The rest of
the INFO block is mt_metadata's (a raw product's run lines come back under
the reader's placeholder run, as in every merge); every line of the
>HEAD, >INFO and >=DEFINEMEAS blocks that differs from the input beyond
FILEDATE and the transform is listed in the record (``writer_changes``)
and counted on the console.

Beside OUT.edi, ``OUT.as_laid.json`` records the site, the survey.yaml,
the input and the output (paths and sha256), the lines transformed (the
declared azimuth, the rows negated, the EMEAS azimuth and electrode ends
before and after, the measurement quoted, the INFO line), the INFO lines
added, the writer changes, the round trip when --check ran, the command
line and the package versions.

--check applies the transform to the written output a second time (the
inverse is the same operation: the rows negated again, the EMEAS line back
to the nominal azimuth, the as-laid INFO lines removed) into a temporary
folder, reads that back with mt_metadata and compares it with the input
read the same way: periods, Z, the Z errors, the tipper and the tipper
errors, every real and imaginary part to the bit (two zeros count as
equal: the EDI holds no value as the EMPTY marker, which reads back as
+0.0 whatever the sign before it). It prints PASS, or FAIL with the first
differing element, and exits 1 on FAIL (the output is kept for
inspection). `check_files` is the same for a caller in Python.

--corrected writes the corrected form from the same
corrected-frame input: for each reversed line no row is negated, the
EMEAS line keeps its nominal azimuth (0 or 90) and its electrode ends, and
one INFO line ``mt_workbench.reversed_ex`` or ``mt_workbench.reversed_ey``
(beside the as-laid key, which only the as-laid mode writes) says "ex laid
reversed; reversal measured <date> (<fragment>), declared in survey.yaml;
the sign was applied at ingest, so the xy row (Zxx, Zxy) is in the nominal
frame and AZM states 0; " followed by ``RULING_R19`` (the measurement quoted as
for the as-laid line, the same fallback sentence). The refusals are the
as-laid mode's (an input already as laid or already marked, a rotation,
`swap_e`, output = input). The record is ``OUT.reversed_lines.json`` with
direction "corrected" and rows_negated []. --check in this mode reads the
output back and compares every period, Z value, Z error, tipper value and
tipper error with the input to the bit (the same rule), and confirms each
INFO line and the nominal AZM; it fails if any differs.

Exit status: 0 written (and, with --check, the round trip PASS), 1 the
round trip FAIL, 2 refused or not written.

Usage:
    python scripts/deliver_as_laid.py <survey.yaml> <in.edi> <out.edi> [--site SITE] [--check] [--corrected]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import difflib
import hashlib
import importlib.metadata
import json
import os
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402

import mt_workbench  # noqa: E402
from mt_workbench import products  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from merge_best import patch_edi_text  # noqa: E402

# each electric line: its impedance row, nominal and as-laid azimuths, the mode its row is, its elements
LINES = {
    "ex": {"row": 0, "nominal": 0.0, "laid": 180.0, "mode": "xy", "elements": ("Zxx", "Zxy"), "name": "Ex"},
    "ey": {"row": 1, "nominal": 90.0, "laid": 270.0, "mode": "yx", "elements": ("Zyx", "Zyy"), "name": "Ey"},
}
INFO_KEY = "mt_workbench.as_laid_"  # + ex or ey: the processing parameter of a line written as laid
PP_PREFIX = "transfer_function.processing_parameters."  # how mt_metadata writes a processing parameter in INFO
RULING = "ruling R5 2026-11-02"
REVERSED_KEY = "mt_workbench.reversed_"  # + ex or ey: the processing parameter of a reversed line delivered corrected
RULING_R19 = "ruling R19 2026-11-05"
NOTHING = "no reversed line; nothing transformed"
ISO = "%Y-%m-%dT%H:%M:%SZ"
# the dated header of a site's notes and the form "polarity measured <date>"
STAGE = re.compile(r"stage \d+ \(agent [^,()]+, (\d{4}-\d{2}-\d{2})\)")
MEASURED = re.compile(r"polarity measured (\d{4}-\d{2}-\d{2})")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# INFO lines the reader turns into other fields and the writer writes back from them: taken from the input's text
RESTORED_INFO = ("transfer_function.processed_date", "provenance.software.name", "provenance.software.version")


class Refused(Exception):
    """A site or an EDI this script does not write as laid (exit 2, nothing written)."""


def sha256(path: Path) -> str:
    """Return the SHA-256 of a file."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ----------------------------------------------------------------------------------------------- the declaration


def clauses(text: str) -> list[str]:
    """Split notes text at the semicolons outside parentheses."""
    out, depth, start = [], 0, 0
    for k, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(depth - 1, 0)
        elif char == ";" and depth == 0:
            out.append(text[start:k])
            start = k + 1
    out.append(text[start:])
    return out


def _after_parenthesis(text: str) -> str:
    """Return the text after a leading parenthesised group (and its nested ones), or the text when it has none."""
    text = text.lstrip()
    if not text.startswith("("):
        return text
    depth = 0
    for k, char in enumerate(text):
        depth += char == "("
        depth -= char == ")"
        if depth == 0:
            return text[k + 1:]
    return ""


def measurement(notes: str | None, comp: str) -> dict | None:
    """Quote the measurement that declared a line reversed from a site's survey.yaml notes.

    The clause (notes split at semicolons outside parentheses) holding
    "<Ex|Ey> declared reversed" gives the measurement: the text after the
    declaration's own parenthesis and colon ("census VIC001 rr VIC006 xy
    -134.7 deg (out; ...)"), prefixed by the dated header that governs it
    (the clause's text before the declaration when ``STAGE`` matches it,
    else the last such header in the clauses before), or, with no text
    after the declaration, the clause's text before it ("polarity measured
    2026-11-02, yx 180 deg out as ingested").

    Args:
        notes (str | None): The site's `notes:`.
        comp (str): "ex" or "ey".

    Returns:
        dict | None: ``{"date", "fragment", "clause"}`` (date "YYYY-MM-DD"
        or None, the quoted fragment, the whole clause); None when no clause
        declares the line reversed.
    """
    if not notes:
        return None
    parts = clauses(" ".join(str(notes).split()))
    # The line's name as a whole word and not after "+": "ey declared reversed" inside "ex+ey declared reversed"
    # is the joint form, which declares both lines (workbench 91).
    pattern = re.compile(rf"(?<![\w+])(?:ex\+ey|ey\+ex|{LINES[comp]['name']}) declared reversed\b", re.I)
    for k, part in enumerate(parts):
        found = pattern.search(part)
        if found is None:
            continue
        before = part[:found.start()].strip()
        after = _after_parenthesis(part[found.end():]).strip()
        census = after[1:].strip() if after.startswith(":") else ""
        if census:
            head = before.rstrip(" :") if STAGE.search(before) else None
            date = STAGE.search(before).group(1) if head else None
            if head is None:
                for earlier in reversed(parts[:k]):
                    hits = list(STAGE.finditer(earlier))
                    if hits:
                        head, date = hits[-1].group(0), hits[-1].group(1)
                        break
            fragment = f"{head}: {census}" if head else census
            if date is None:
                found_date = DATE.search(census)
                date = found_date.group(0) if found_date else None
        else:
            fragment = re.sub(r"[\s,:]*(?:\bso\b|\band\b)?[\s,:]*$", "", before)
            if not fragment:
                continue
            found_date = MEASURED.search(fragment)
            date = found_date.group(1) if found_date else (DATE.search(fragment).group(0)
                                                           if DATE.search(fragment) else None)
        return {"date": date, "fragment": fragment, "clause": part.strip()}
    return None


def info_text(comp: str, found: dict | None) -> str:
    """Return the value of a reversed line's INFO line (the text after ``mt_workbench.as_laid_<comp>=``)."""
    spec = LINES[comp]
    if found is None:
        source = "reversal declared in survey.yaml"
    else:
        when = f" {found['date']}" if found["date"] else ""
        source = f"reversal measured{when} ({found['fragment']}), declared in survey.yaml"
    text = (f"{comp} written as laid: AZM {spec['laid']:g}; the {spec['mode']} row ({', '.join(spec['elements'])}) "
            f"is the field as measured on the reversed dipole; a reader assuming north and east sees it 180 deg out, "
            f"a reader honouring AZM recovers the tensor; {source}; {RULING}")
    return products._safe(text)


def reversed_text(comp: str, found: dict | None) -> str:
    """Return the value of a reversed line's corrected-mode INFO line (after ``mt_workbench.reversed_<comp>=``)."""
    spec = LINES[comp]
    if found is None:
        source = "reversal declared in survey.yaml"
    else:
        when = f" {found['date']}" if found["date"] else ""
        source = f"reversal measured{when} ({found['fragment']}), declared in survey.yaml"
    text = (f"{comp} laid reversed; {source}; the sign was applied at ingest, so the {spec['mode']} row "
            f"({', '.join(spec['elements'])}) is in the nominal frame and AZM states {spec['nominal']:g}; {RULING_R19}")
    return products._safe(text)


def declaration(survey: Survey, site: str) -> tuple[list[str], str | None, str]:
    """Return the lines a site declares measured reversed, the notes naming the measurement, and the site read.

    Args:
        survey (Survey): The survey.
        site (str): The site, with its own entry in survey.yaml's `sites:`.

    Returns:
        tuple: ``(lines, notes, declared_by)``: the reversed lines ("ex",
        "ey" in that order), the notes of the site whose ingest made the
        correction (a derived site's parent), and that site's name.

    Raises:
        Refused: No entry; survey.yaml refuses the site; a derived site
            whose azimuths, swap_e or flip_reversed_dipoles differ from its
            parent's; `swap_e`; an azimuth neither nominal nor reversed; a
            reversed azimuth under `flip_reversed_dipoles: false`.
    """
    if site not in survey.site_names():
        raise Refused(f"site {site!r} has no entry in survey.yaml's sites: block: no declaration to read "
                      f"(--site names the site when the DATAID is not it)")
    try:
        config = survey.site(site)
        parent = survey.parent_of(site)
        source = survey.site(parent) if parent else config
    except ValueError as exc:
        raise Refused(f"survey.yaml refuses site {site!r}: {exc}") from exc
    if parent:
        own = (config.azimuth_ex % 360.0, config.azimuth_ey % 360.0, config.swap_e, config.flip_reversed_dipoles)
        theirs = (source.azimuth_ex % 360.0, source.azimuth_ey % 360.0, source.swap_e, source.flip_reversed_dipoles)
        if own != theirs:
            raise Refused(f"{site} is derived from {parent} and declares (azimuth_ex, azimuth_ey, swap_e, "
                          f"flip_reversed_dipoles) {own}, {parent} {theirs}: its archive carries {parent}'s "
                          f"correction, so the two must agree")
    if source.swap_e:
        raise Refused(f"{source.name}: swap_e: true (its electric lines were exchanged at ingest): the as-laid form "
                      f"of an exchanged pair is not built here; nothing written")
    lines = []
    for comp, spec in LINES.items():
        azimuth = float(getattr(source, f"azimuth_{comp}"))
        off = (azimuth - spec["nominal"]) % 360.0
        if off == 0.0:
            continue
        if off != 180.0:
            raise Refused(f"{source.name} {comp}: azimuth {azimuth:g} is neither {spec['nominal']:g} nor "
                          f"{spec['laid']:g}: a line at another angle is a rotation; not "
                          f"built here")
        if not source.flip_reversed_dipoles:
            raise Refused(f"{source.name} {comp}: azimuth {azimuth:g} under flip_reversed_dipoles: false: the ingest "
                          f"did not negate the line (the azimuth is read as the layout direction only), so there is "
                          f"no correction to undo; not built here")
        lines.append(comp)
    return lines, source.notes, source.name


# ------------------------------------------------------------------------------------------------ the EDI's text


def processing_parameters(text: str) -> list[str]:
    """Return the processing-parameter lines of an EDI's INFO block as written (keys with "mt_workbench.").

    mt_metadata's reader keeps only the last dotted part of each key
    ("mt_workbench.flag_001=" comes back as "flag_001="), so the lines are
    taken from the text.
    """
    head = text.split(">=DEFINEMEAS")[0]
    return [line.strip()[len(PP_PREFIX):] for line in head.splitlines() if line.strip().startswith(PP_PREFIX)]


def info_value(text: str, key: str) -> str | None:
    """Return the value of an INFO line ``key=value`` of an EDI's text, None when it has none."""
    head = text.split(">=DEFINEMEAS")[0]
    for line in head.splitlines():
        body = line.strip()
        if body.split("=", 1)[0].strip().lower() == key.lower() and "=" in body:
            return body.split("=", 1)[1].strip()
    return None


def head_value(text: str, key: str) -> str | None:
    """Return the value of a >HEAD line, None when the block lacks it."""
    head = text.split(">INFO")[0]
    for line in head.splitlines():
        body = line.strip()
        if "=" in body and body.split("=", 1)[0].strip().upper() == key.upper():
            return body.split("=", 1)[1].strip().strip('"')
    return None


def measurement_lines(text: str) -> dict[str, dict]:
    """Return an EDI's EMEAS and HMEAS lines by channel: ``{"kind": "E" or "H", "line": str, "fields": {...}}``."""
    out = {}
    for line in text.splitlines():
        found = re.match(r"\s*>([EH])MEAS\s+(.*)", line)
        if not found:
            continue
        fields = dict(re.findall(r"(\w+)=(\S+)", found.group(2)))
        comp = fields.get("CHTYPE", "").lower()
        if comp:
            out[comp] = {"kind": found.group(1), "line": line.strip(), "fields": fields}
    return out


def _number(text: str | None, default: float = 0.0) -> float:
    """Return a measurement-line field as a float."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return default


def geometry_of(tf, lines: dict[str, dict]) -> dict[str, dict]:
    """Return the channel geometry the input's measurement lines state, in `products.archive_geometry`'s form.

    Each channel: ``azimuth`` (AZM), for a magnetic one ``tilt`` (DIP), for
    an electric one ``dipole_length`` (the TF's own channel) and the ends
    ``negative`` (X, Y) and ``positive`` (X2, Y2).
    """
    lengths = {}
    for run in tf.station_metadata.runs:
        for ch in run.channels:
            if ch.component and getattr(ch, "dipole_length", None) is not None:
                lengths.setdefault(str(ch.component).lower(), float(ch.dipole_length))
    out = {}
    for comp, entry in lines.items():
        f = entry["fields"]
        g = {"azimuth": _number(f.get("AZM"))}
        if entry["kind"] == "E":
            g.update({"dipole_length": lengths.get(comp, 0.0), "negative": (_number(f.get("X")), _number(f.get("Y"))),
                      "positive": (_number(f.get("X2")), _number(f.get("Y2")))})
        else:
            g["tilt"] = _number(f.get("DIP"))
        out[comp] = g
    return out


def keep_channel_numbers(tf, lines: dict[str, dict]) -> None:
    """Set each channel's number to the one the input's ACQCHAN states, so the writer writes ACQCHAN as it was.

    mt_metadata writes a channel number of 0 as the line's ID ("ACQCHAN=3.0"
    for hx, ID=3.0) and reads that back as 30 (upstream 497): an ACQCHAN
    whose text is the ID's is a 0; any other is its number ("3" is 3).
    """
    for run in tf.station_metadata.runs:
        for ch in run.channels:
            entry = lines.get(str(ch.component).lower()) if ch.component else None
            if entry is None:
                continue
            fields = entry["fields"]
            acqchan = fields.get("ACQCHAN")
            try:
                ch.channel_number = 0 if acqchan == fields.get("ID") else int(float(acqchan))
            except (TypeError, ValueError):
                continue


# ------------------------------------------------------------------------------------------------- the transform


def as_laid(tf, comps: list[str], geometry: dict[str, dict], laid: bool = True) -> None:
    """Write the named lines as laid (or back to nominal), in place: rows negated, EMEAS azimuth and ends set.

    The impedance rows of the lines are negated, real and imaginary parts
    (the same operation in both directions); the errors and the tipper are
    left as they are. Each line's geometry gets the as-laid azimuth (180,
    270) or, with ``laid=False``, the nominal one (0, 90); electrode ends
    that are not all zero are exchanged.

    Args:
        tf (TF): The transfer function, changed in place.
        comps (list[str]): The lines, "ex" and/or "ey".
        geometry (dict): `geometry_of`'s form, changed in place.
        laid (bool): True for as laid, False for nominal.
    """
    z = np.array(tf.impedance.data)
    for comp in comps:
        row = LINES[comp]["row"]
        z[:, row, :] = -z[:, row, :]
        g = geometry[comp]
        g["azimuth"] = LINES[comp]["laid" if laid else "nominal"]
        if any(g["negative"]) or any(g["positive"]):
            g["negative"], g["positive"] = g["positive"], g["negative"]
    tf.impedance = z


def _block_lines(text: str) -> list[str]:
    """Return the >HEAD, >INFO and >=DEFINEMEAS lines of an EDI (everything before its data), stripped."""
    end = text.find(">=MTSECT")
    return [line.strip() for line in (text if end < 0 else text[:end]).splitlines() if line.strip()]


def writer_changes(before: str, after: str, comps: list[str]) -> list[str]:
    """List the header lines of the written EDI that differ from the input beyond FILEDATE and the transform.

    Lines of the >HEAD, >INFO and >=DEFINEMEAS blocks, as a unified diff
    without context ("-" the input's, "+" the output's); FILEDATE, the
    as-laid INFO lines, each transformed line's EMEAS line and its run
    measurement_azimuth line are left out.
    """
    expected = ("FILEDATE=", PP_PREFIX + INFO_KEY, PP_PREFIX + REVERSED_KEY)
    run_azimuth = tuple(f".{comp}.measurement_azimuth=" for comp in comps)
    out = []
    for line in difflib.unified_diff(_block_lines(before), _block_lines(after), lineterm="", n=0):
        if line.startswith(("---", "+++", "@@")):
            continue
        body = line[1:]
        if body.startswith(expected) or any(key in body for key in run_azimuth) or (
                body.startswith(">EMEAS") and any(re.search(rf"\bCHTYPE={comp}\b", body) for comp in comps)):
            continue
        out.append(line)
    return out


def transform_file(survey_path, in_edi, out_edi, site: str | None = None, laid: bool = True,
                   corrected: bool = False) -> dict:
    """Write an EDI with the site's measured-reversed lines as laid (or, with laid=False, back to nominal).

    Args:
        survey_path (str | Path): survey.yaml.
        in_edi (str | Path): The EDI to read.
        out_edi (str | Path): The EDI to write.
        site (str | None): The site; the EDI's DATAID when None.
        laid (bool): True writes as laid (the delivery); False the inverse
            (`check_files`' round trip).
        corrected (bool): True writes the corrected form
            instead: no row negated, AZM nominal, a ``mt_workbench.reversed_*``
            INFO line per reversed line (the as-laid refusals apply).

    Returns:
        dict: The record (the ``.as_laid.json`` content without the check).

    Raises:
        Refused: Nothing written (see the module docstring).
    """
    in_edi, out_edi = Path(in_edi).resolve(), Path(out_edi).resolve()
    if in_edi == out_edi:
        raise Refused(f"the output {out_edi} is the input: write the delivered EDI to another path")
    text = in_edi.read_text(encoding="latin-1")
    tf = products.read_tf(in_edi)
    site = site or str(tf.station_metadata.id)
    survey = Survey.from_yaml(survey_path)
    comps, notes, declared_by = declaration(survey, site)

    lines = measurement_lines(text)
    params = processing_parameters(text)
    marked = [p for p in params if p.split("=", 1)[0].strip().startswith(INFO_KEY)]
    for comp in comps:
        if comp not in lines:
            raise Refused(f"{in_edi.name}: no EMEAS line for {comp}, declared reversed at {declared_by}")
    azimuths = {comp: _number(lines[comp]["fields"].get("AZM")) for comp in comps}
    if corrected:
        laid = True  # the as-laid refusals below apply to the corrected form too
        noted = [p for p in params if p.split("=", 1)[0].strip().startswith(REVERSED_KEY)]
        if noted:
            raise Refused(f"{in_edi.name} already carries {noted[0].split('=', 1)[0]}: the corrected form is written "
                          f"once")
    if laid:
        if marked:
            raise Refused(f"{in_edi.name} is already written as laid ({marked[0].split('=', 1)[0]}): the transform "
                          f"is applied once")
        done = [comp for comp in comps if azimuths[comp] % 360.0 == LINES[comp]["laid"]]
        if done:
            raise Refused(f"{in_edi.name}: EMEAS {done[0]} already states AZM {azimuths[done[0]]:g}, the azimuth as "
                          f"laid: the transform is applied once")
    else:
        wrong = [comp for comp in comps if azimuths[comp] % 360.0 != LINES[comp]["laid"]]
        if wrong:
            raise Refused(f"{in_edi.name}: EMEAS {wrong[0]} states AZM {azimuths[wrong[0]]:g}, not as laid: nothing "
                          f"to turn back")

    geometry = geometry_of(tf, lines)
    before = {comp: copy.deepcopy(geometry[comp]) for comp in comps}
    if not corrected:  # the corrected form negates no row and keeps the nominal azimuth and the electrode ends
        as_laid(tf, comps, geometry, laid=laid)
    found = {comp: measurement(notes, comp) for comp in comps}
    added = [f"{INFO_KEY}{comp}={info_text(comp, found[comp])}" for comp in comps] if laid else []
    if corrected:
        added = [f"{REVERSED_KEY}{comp}={reversed_text(comp, found[comp])}" for comp in comps]
    sm = tf.station_metadata
    sm.transfer_function.processing_parameters = [p for p in params if p not in marked] + added
    # the survey's products.zrot, as scripts/process_rr.py sets it: ZROT and TROT follow the survey
    # delivered to, not the rule line the input EDI happens to carry
    products.set_zrot_rule(tf, products.zrot_rule_of(survey))
    keep_channel_numbers(tf, lines)
    for key in RESTORED_INFO:
        value = info_value(text, key)
        target, attr = (sm.transfer_function, "processed_date") if key.startswith("transfer_function") else (
            sm.provenance.software, key.rsplit(".", 1)[1])
        setattr(target, attr, value if value not in ("", None) else None)
    credits = (("acqby", head_value(text, "ACQBY")), ("prosby", head_value(text, "PROSBY")))
    header = {key: value for key, value in credits if value}

    out_edi.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_edi.with_name(out_edi.stem + "_part.edi")
    products.write_edi(tf, tmp, geometry=geometry)
    # mt_metadata's writer opens its file with the locale's encoding: read and write it back the same way
    with open(tmp, encoding="locale", newline="") as handle:
        written = handle.read()
    with open(tmp, "w", encoding="locale", newline="") as handle:
        handle.write(patch_edi_text(written, header))
    # the written text is read back: on a mismatch the part file stays for inspection and is not delivered
    out_text = tmp.read_text(encoding="latin-1")
    out_lines = measurement_lines(out_text)
    for comp in comps:
        want = LINES[comp]["laid" if laid else "nominal"]
        want = LINES[comp]["nominal"] if corrected else want
        got = _number(out_lines.get(comp, {}).get("fields", {}).get("AZM"), float("nan"))
        if got != want:
            raise RuntimeError(f"{tmp.name}: EMEAS {comp} AZM {got:g} written, {want:g} intended; not delivered")
    out_params = processing_parameters(out_text)
    for line in added:
        if line not in out_params:
            raise RuntimeError(f"{tmp.name}: the INFO line {line.split('=', 1)[0]} was not written as given; not "
                               f"delivered")
    os.replace(tmp, out_edi)

    period = np.asarray(tf.period, dtype=float)
    z = np.asarray(tf.impedance.data)
    record = {
        "site": site,
        "declared_by": declared_by,
        "direction": "as laid" if laid else "nominal (the inverse)",
        "survey_yaml": {"path": str(Path(survey_path).resolve()), "sha256": sha256(Path(survey_path))},
        "input": {"path": str(in_edi), "sha256": sha256(in_edi)},
        "output": {"path": str(out_edi), "sha256": sha256(out_edi)},
        "n_periods": int(period.size),
        "transformed": [] if comps else NOTHING,
        "info_lines_added": [PP_PREFIX + line for line in added],
        "info_lines_removed": [PP_PREFIX + line for line in marked] if not laid else [],
        "header_patch": header,
    }
    for comp in comps:
        spec = LINES[comp]
        record["transformed"].append({
            "line": comp,
            "declared_azimuth": spec["laid"],
            "rows_negated": list(spec["elements"]),
            "row_empty_periods": int(np.sum(np.all(z[:, spec["row"], :] == 0, axis=1))),
            "emeas_azimuth": {"before": azimuths[comp], "after": geometry[comp]["azimuth"]},
            "electrode_ends": {"before": {"negative": list(before[comp]["negative"]),
                                          "positive": list(before[comp]["positive"])},
                               "after": {"negative": list(geometry[comp]["negative"]),
                                         "positive": list(geometry[comp]["positive"])},
                               "exchanged": bool(any(before[comp]["negative"]) or any(before[comp]["positive"]))},
            "measurement": found[comp],
            "info_line": (PP_PREFIX + added[comps.index(comp)]) if laid else None,
        })
    if corrected:  # the corrected form: no row negated, no ends exchanged; the EMEAS lines are compared whole below
        record["direction"] = "corrected"
        record["ruling"] = RULING_R19
        record["rows_negated"] = []
        for entry in record["transformed"] if comps else []:
            entry["rows_negated"] = []
            entry["electrode_ends"]["exchanged"] = False
        record["writer_changes"] = writer_changes(text, out_text, [])
        return record
    record["writer_changes"] = writer_changes(text, out_text, comps)
    return record


# ------------------------------------------------------------------------------------------------- the round trip


def same_bits(a, b) -> np.ndarray:
    """Flag the elements of two float arrays that are equal to the bit (two zeros, or two NaN, count as equal)."""
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"shapes {a.shape} and {b.shape} differ")
    return (a.view(np.int64) == b.view(np.int64)) | ((a == 0) & (b == 0)) | (np.isnan(a) & np.isnan(b))


def _parts(tf) -> dict[str, np.ndarray]:
    """Return the arrays the round trip compares, by name (complex arrays split into real and imaginary)."""
    out = {"period": np.asarray(tf.period, dtype=float)}
    z = np.asarray(tf.impedance.data)
    out["Z real"], out["Z imag"] = z.real, z.imag
    out["Z error"] = np.asarray(tf.impedance_error.data, dtype=float) if tf.impedance_error is not None else None
    if tf.has_tipper():
        t = np.asarray(tf.tipper.data)
        out["T real"], out["T imag"] = t.real, t.imag
        out["T error"] = np.asarray(tf.tipper_error.data, dtype=float) if tf.tipper_error is not None else None
    return out


def _element(name: str, index: tuple, period) -> str:
    """Name an element of a compared array: "Zxy real at period 12.3 s (index 4)"."""
    if name == "period":
        return f"period (index {index[0]})"
    kind, part = name.split(" ")
    if kind == "Z":
        label = "Z" + "xy"[index[1]] + "xy"[index[2]]
    else:
        label = "T" + "xy"[index[2]]
    return f"{label} {part} at period {period[index[0]]:.6g} s (index {index[0]})"


def first_difference(tf_a, tf_b) -> str | None:
    """Return the first element where two TFs' periods, Z, Z errors, tipper or tipper errors differ, None when none.

    Every real and imaginary part is compared to the bit (`same_bits`).
    """
    a, b = _parts(tf_a), _parts(tf_b)
    if set(a) != set(b):
        return f"arrays held: {sorted(a)} against {sorted(b)}"
    period = a["period"]
    for name in a:
        if (a[name] is None) != (b[name] is None):
            return f"{name}: present in one only"
        if a[name] is None:
            continue
        if a[name].shape != b[name].shape:
            return f"{name}: shape {a[name].shape} against {b[name].shape}"
        bad = np.argwhere(~same_bits(a[name], b[name]))
        if bad.size:
            index = tuple(int(i) for i in bad[0])
            return (f"{_element(name, index, period)}: input {float(a[name][index])!r}, round trip "
                    f"{float(b[name][index])!r} ({bad.shape[0]} element(s) of {name} differ)")
    return None


def round_trip(survey_path, in_edi, out_edi, site: str | None = None, folder=None):
    """Apply the transform to a written output a second time and read back both ends.

    Args:
        survey_path, in_edi, out_edi: As for `transform_file`.
        site (str | None): The site; the input's DATAID when None.
        folder (str | Path | None): Where the twice-transformed EDI goes; a
            temporary folder when None.

    Returns:
        tuple: ``(tf_in, tf_back)``, the input and the twice-transformed
        output as mt_metadata reads them.
    """
    tf_in = products.read_tf(in_edi)
    site = site or str(tf_in.station_metadata.id)
    if folder is not None:
        back = Path(folder) / (Path(out_edi).stem + "_back.edi")
        transform_file(survey_path, out_edi, back, site=site, laid=False)
        return tf_in, products.read_tf(back)
    with tempfile.TemporaryDirectory(prefix="as_laid_check_") as tmp:
        back = Path(tmp) / (Path(out_edi).stem + "_back.edi")
        transform_file(survey_path, out_edi, back, site=site, laid=False)
        return tf_in, products.read_tf(back)


def check_files(survey_path, in_edi, out_edi, site: str | None = None) -> dict:
    """The --check: the round trip compared with the input to the bit.

    Returns:
        dict: ``{"result": "PASS" or "FAIL", "first_difference": str or
        None, "compared": [...]}``.
    """
    tf_in, tf_back = round_trip(survey_path, in_edi, out_edi, site)
    diff = first_difference(tf_in, tf_back)
    return {"result": "FAIL" if diff else "PASS", "first_difference": diff,
            "compared": list(_parts(tf_in)), "rule": "every real and imaginary part to the bit; two zeros (EMPTY) "
                                                     "or two NaN equal"}


def check_corrected(survey_path, in_edi, out_edi, site: str | None = None) -> dict:
    """The --check of the corrected mode: the output read back against the input, and its text.

    Every period, Z value, Z error, tipper value and tipper error of the
    output equals the input's to the bit (`first_difference`, no transform
    applied); each reversed line's EMEAS line states its nominal azimuth; the
    output carries each reversed line's ``mt_workbench.reversed_*`` INFO line
    with the text this script writes and no ``mt_workbench.as_laid_*`` line.

    Returns:
        dict: ``{"result": "PASS" or "FAIL", "first_difference": str or
        None, "compared": [...], "rule": str}``; first_difference names the
        first failing element or text check.
    """
    tf_in, tf_out = products.read_tf(in_edi), products.read_tf(out_edi)
    site = site or str(tf_in.station_metadata.id)
    comps, notes, _declared_by = declaration(Survey.from_yaml(survey_path), site)
    diff = first_difference(tf_in, tf_out)
    if diff:
        diff = diff.replace(", round trip ", ", output ")
    text = Path(out_edi).read_text(encoding="latin-1")
    params = processing_parameters(text)
    lines = measurement_lines(text)
    problems = [] if diff is None else [diff]
    for comp in comps:
        want = f"{REVERSED_KEY}{comp}={reversed_text(comp, measurement(notes, comp))}"
        if want not in params:
            problems.append(f"the INFO line {REVERSED_KEY}{comp} is missing or not as written")
        got = _number(lines.get(comp, {}).get("fields", {}).get("AZM"), float("nan"))
        if got != LINES[comp]["nominal"]:
            problems.append(f"EMEAS {comp} states AZM {got:g}, not the nominal {LINES[comp]['nominal']:g}")
    marked = [p.split("=", 1)[0] for p in params if p.split("=", 1)[0].strip().startswith(INFO_KEY)]
    if marked:
        problems.append(f"an as-laid INFO line is present ({marked[0]})")
    return {"result": "FAIL" if problems else "PASS", "first_difference": problems[0] if problems else None,
            "problems": problems, "compared": list(_parts(tf_in)) + ["reversed INFO lines", "EMEAS AZM nominal"],
            "rule": "every real and imaginary part of the output equal to the input's to the bit (two zeros or two "
                    "NaN equal); the INFO line and the nominal AZM of each reversed line; no as-laid INFO line"}


# ----------------------------------------------------------------------------------------------------------- main


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip(),
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("survey", help="survey.yaml")
    parser.add_argument("input", help="the EDI to deliver (corrected frame)")
    parser.add_argument("output", help="the delivered EDI to write")
    parser.add_argument("--site", default=None, help="the site in survey.yaml (default: the EDI's DATAID)")
    parser.add_argument("--check", action="store_true", help="apply the transform to the output again and compare "
                                                             "with the input to the bit")
    parser.add_argument("--corrected", action="store_true", help="write every row in the nominal frame "
                                                                 "(nothing negated, AZM nominal) with an INFO line per "
                                                                 "reversed line; record OUT.reversed_lines.json")
    args = parser.parse_args(argv)
    if args.corrected:
        return main_corrected(args, argv)
    out = Path(args.output).resolve()
    try:
        record = transform_file(args.survey, args.input, out, site=args.site)
    except Refused as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    record.update({"created": dt.datetime.now(dt.timezone.utc).strftime(ISO),
                   "argv": list(sys.argv if argv is None else argv),
                   "versions": {"mt_workbench": mt_workbench.__version__,
                                "mt_metadata": importlib.metadata.version("mt_metadata")}})
    if record["transformed"] == NOTHING:
        print(f"{record['site']}: {NOTHING}; the input re-written by the same writer")
    for entry in record["transformed"] if isinstance(record["transformed"], list) else []:
        empty = entry["row_empty_periods"]
        print(f"{record['site']} {entry['line']}: {', '.join(entry['rows_negated'])} negated at "
              f"{record['n_periods']} periods" + (f" ({empty} of them EMPTY, written EMPTY)" if empty else "")
              + f"; EMEAS AZM {entry['emeas_azimuth']['before']:.2f} -> {entry['emeas_azimuth']['after']:.2f}"
              + ("; electrode ends exchanged" if entry["electrode_ends"]["exchanged"] else ""))
        print(f"  INFO {entry['info_line']}")
    if record["writer_changes"]:
        print(f"WARNING {len(record['writer_changes'])} header line(s) differ from the input beyond FILEDATE and the "
              f"transform (mt_metadata's writer; listed in the record's writer_changes)")
    status = 0
    if args.check:
        try:
            record["check"] = check_files(args.survey, args.input, out, site=record["site"])
        except (Refused, OSError, ValueError, RuntimeError) as exc:
            record["check"] = {"result": "FAIL", "first_difference": f"the inverse was not written: {exc}"}
        if record["check"]["result"] == "PASS":
            print(f"PASS round trip: the output transformed again equals the input to the bit "
                  f"({', '.join(record['check']['compared'])})")
        else:
            print(f"FAIL round trip: {record['check']['first_difference']}")
            status = 1
    side = out.with_suffix(".as_laid.json")
    tmp = side.with_name(side.name + ".part")
    tmp.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, side)
    print(f"edi: {out}")
    print(f"record: {side}")
    return status


def main_corrected(args, argv=None) -> int:
    """The --corrected command line: write, optionally check, and record OUT.reversed_lines.json."""
    out = Path(args.output).resolve()
    try:
        record = transform_file(args.survey, args.input, out, site=args.site, corrected=True)
    except Refused as exc:
        print(f"REFUSED {exc}", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    record.update({"created": dt.datetime.now(dt.timezone.utc).strftime(ISO),
                   "argv": list(sys.argv if argv is None else argv),
                   "versions": {"mt_workbench": mt_workbench.__version__,
                                "mt_metadata": importlib.metadata.version("mt_metadata")}})
    if record["transformed"] == NOTHING:
        print(f"{record['site']}: {NOTHING}; the input re-written by the same writer")
    for entry in record["transformed"] if isinstance(record["transformed"], list) else []:
        print(f"{record['site']} {entry['line']}: laid reversed, delivered corrected: no row negated at "
              f"{record['n_periods']} periods; EMEAS AZM {entry['emeas_azimuth']['after']:.2f} (nominal)")
        print(f"  INFO {entry['info_line']}")
    if record["writer_changes"]:
        print(f"WARNING {len(record['writer_changes'])} header line(s) differ from the input beyond FILEDATE and the "
              f"INFO lines added (mt_metadata's writer; listed in the record's writer_changes)")
    status = 0
    if args.check:
        try:
            record["check"] = check_corrected(args.survey, args.input, out, site=record["site"])
        except (Refused, OSError, ValueError, RuntimeError) as exc:
            record["check"] = {"result": "FAIL", "first_difference": f"the output was not read back: {exc}"}
        if record["check"]["result"] == "PASS":
            print(f"PASS corrected: the output equals the input to the bit "
                  f"({', '.join(record['check']['compared'])})")
        else:
            print(f"FAIL corrected: {record['check']['first_difference']}")
            status = 1
    side = out.with_suffix(".reversed_lines.json")
    tmp = side.with_name(side.name + ".part")
    tmp.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, side)
    print(f"edi: {out}")
    print(f"record: {side}")
    return status


if __name__ == "__main__":
    sys.exit(main())
