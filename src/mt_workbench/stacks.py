# -*- coding: utf-8 -*-
"""
Stack recipes declared per survey in `<survey>/stacks.yaml`

A stack recipe names a stack once, for both stack engines: its field (H or
E), its use, its method, its sample rate, its members (a rule or a list),
its window and the method's parameters. The file is edited by hand; the GUI
Stacks tab writes it when the user clicks Save, and the scripts read it:

    STK_D13:
      field: H
      use: remote
      method: time_mean
      sample_rate: 1000.0
      members: [D10, D11, D12, D14, D15]
      start: 2023-09-19 19:02
      end: 2023-09-21 07:02
      use_filters: true

Methods (`METHODS`). The band methods, `band_mean` and `band_median`, are
formed per band inside each run of scripts/process_intersite.py
(``--stack NAME``), as the base stack (``use: base``) or the reference
(``use: reference``), and held for that run alone. The time methods,
`time_mean` and `time_coherence`, are an archive written by
scripts/build_stack.py ``--recipe NAME`` for scripts/process_rr.py
(``use: remote``), and take an explicit member list of at least two sites,
so the station the archive is later the remote of stays outside it. The
median is a band method alone: a sample-wise median follows the member in the
middle of whatever dominates the samples and carries that member's noise
into every other band.

Keys (`applicable_keys` gives the ones a method and use take, in the order
the file holds them): ``field``, ``use``, ``method``, ``sample_rate``,
``members`` (``rule`` or a list), ``exclude`` (with ``rule`` only),
``min_overlap_hours``, ``start`` and ``end`` (UTC, written
``YYYY-MM-DD HH:MM``; seconds must be 0; a zone-aware time is converted to
UTC), ``reject_factor``, ``min_members``, ``screen_polarity`` and
``member_change`` (band base stacks), ``use_filters`` and ``notes``.
`Recipe.from_mapping` checks every key and fills the defaults, and raises
`StacksError` naming the recipe and the key. One optional ``chart`` block
holds the Stacks tab's reference sites and night (`load_chart`).

A time_coherence window spans at least `COHERENCE_MIN_S`: the coherence
weights are taken per `mt_workbench.virtual.WEIGHT_CHUNK_S` chunk, and
`mt_workbench.virtual.member_coherence` plans its band ladder with one window
per chunk and `COHERENCE_MIN_CHUNKS` windows at the least. A shorter recipe
is refused when it is read, so the Stacks tab's Save and build_stack.py
--recipe name the minimum before any build starts.

Writing (`save_recipe`, `save_chart`) replaces one block and carries every
other byte over. A block is a column-0 key line and its indented lines;
column-0 comment lines are never part of one, so a save drops no lead
comment and no commented-out recipe, and a column-0 comment found between a
saved block's indented lines is moved to just below the new block. Comments
indented inside a saved block are lost. The file is read and written as
bytes and keeps its own newline (that of its first line), and the write goes
through a temporary file and `os.replace`, so a reader never sees a part
written file. `mt_workbench.masks.replace_text` is not used: it writes
through `Path.write_text`, which turns an LF file into CRLF on Windows
(docs/workbench_issues.md 25).

Reading parses a file once per change, as `mt_workbench.masks.read_document`
does: the result is kept per path with the file's modification time and
size, and a file modified within `mt_workbench.masks.RACY_S` of its read is
read again next time. Two key lines with one name make the whole file an
error (PyYAML would keep the last one without a word), as do text that is
not YAML or not a mapping and a top-level key that is neither ``STK_...``
nor ``chart``. An invalid recipe makes only that recipe an error
(`load_recipes`).

The recipe hash (`recipe_hash`) is the first 12 hex digits of the SHA-256
of the canonical text (`canonical_text`): the applicable keys with their
defaults, lists sorted and unique, times as ``YYYY-MM-DDTHH:MM:SSZ``,
without the name and the notes. A rename or a new remark keeps the hash.
Products made from a recipe record its name, hash and canonical text
(`provenance`).

Members (`resolve_members`) are chosen by `mt_workbench.intersite.select_stack`
at the recipe's rate: the rule takes every site covering the window, a list
leaves the other sites out (`NOT_LISTED`), and a listed name with no entry
in survey.yaml is reported (`NO_ENTRY`). A time recipe's member is judged by
its single run that overlaps the window most (`best_run`), as
`mt_workbench.virtual` builds it, and needs that run to cover the window
less `mt_workbench.intersite.MEMBER_EDGE_S`.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import codecs
import datetime as dt
import hashlib
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, NamedTuple

import pandas as pd
import yaml
from loguru import logger

from . import intersite
from .masks import _LOADER, RACY_S, REPLACE_TRIES, _Dumper
from .virtual import WEIGHT_CHUNK_S

STACKS_FILE = "stacks.yaml"
CHART_KEY = "chart"
MEMBER_RULE = "rule"
NAME_RE = re.compile(r"^STK_[A-Za-z0-9]+(_[A-Za-z0-9]+)*$")
NAME_MAX = 40  # characters in a recipe name
USES = ("base", "reference", "remote")
POLARITY = ("flag", "drop")
MEMBER_CHANGE = ("constant", "allow")
DEFAULT_METHOD = "band_mean"
# the windows of virtual.member_coherence's ladder: timefreq.levels_plan's default min_windows, one window per chunk
COHERENCE_MIN_CHUNKS = 3
COHERENCE_MIN_S = COHERENCE_MIN_CHUNKS * WEIGHT_CHUNK_S  # the shortest time_coherence window, in s
# scripts/gate_masks.py's NIGHT: local time in survey.timezone; a script cannot be imported from src
DEFAULT_NIGHT = "01:00-05:00"
NOT_LISTED = "not among the recipe's members"
NO_ENTRY = "no entry in survey.yaml"
# the tensor a base stack of each field makes: {"E": "telluric", "H": "magnetic"}
KIND_OF_BASE = {field: kind for kind, field in intersite.BASE_FIELDS.items()}
TIME_FMT = "%Y-%m-%d %H:%M"  # how start and end are written
CANONICAL_TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"
# every recipe key, in the order a block holds them
KEYS = ("field", "use", "method", "sample_rate", "members", "exclude", "min_overlap_hours", "start", "end",
        "reject_factor", "min_members", "screen_polarity", "member_change", "use_filters", "notes")
_BAND_ONLY = ("exclude", "min_overlap_hours", "reject_factor", "min_members")
_BASE_ONLY = ("screen_polarity", "member_change")
CHART_KEYS = ("references", "night")
HEADER = (
    "# Stack recipes declared on the GUI's Stacks tab (mt_workbench.stacks): per stack, its sites,\n"
    "# field, window and method. scripts/process_intersite.py --stack NAME forms a band recipe inside\n"
    "# each run; scripts/build_stack.py --recipe NAME writes a time recipe's archive\n"
    "# <workspace>/mth5/NAME.h5 for scripts/process_rr.py. Times are UTC, written YYYY-MM-DD HH:MM.\n"
    "# The tab rewrites only the recipe it saves: its key line and its indented lines. Comment lines\n"
    "# that start in column 0 are never touched; comments indented inside a recipe are lost when that\n"
    "# recipe is saved, so keep remarks in notes:.\n"
)
_NIGHT_RE = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])-([01][0-9]|2[0-3]):([0-5][0-9])$")
# text a time may be written as: a date, an optional HH:MM[:SS[.f]] and an optional zone
_TIME_TEXT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?)?[ ]*(Z|[+-]\d{2}(:?\d{2})?)?$")
# a column-0 key line: a plain or quoted key, then a colon followed by a space or the line's end
_KEY_LINE = re.compile(r"""^(?P<q>['"]?)(?P<name>[^\s'"#:\-][^'":]*?)(?P=q)[ \t]*:(?:[ \t\r]|$)""")
_BOM = codecs.BOM_UTF8
_LOCK = threading.Lock()
# parsed files: absolute path -> ((st_mtime_ns, st_size), the bytes when read within RACY_S of a write
# else None, the parse)
_PARSED: dict[str, tuple[tuple[int, int], bytes | None, "_Parse"]] = {}


class StacksError(ValueError):
    """A stacks.yaml that cannot be used: a file error, or an invalid recipe or chart block."""


@dataclass(frozen=True)
class Method:
    """One stacking method a recipe may name.

    Attributes:
        key (str): The recipe's ``method`` value.
        engine (str): ``"band"`` (formed per band inside each
            process_intersite run) or ``"time"`` (an archive written by
            build_stack.py).
        label (str): The text of the GUI's method dropdown.
        uses (tuple): The ``use`` values the method takes.
        fields (tuple): The fields the method takes.
        stack (str): ``"mean"`` or ``"median"``: the band engine's
            ``method=`` (``"mean"`` for the time methods).
        weighting (str or None): ``"none"`` or ``"coherence"``, virtual's
            ``weighting=`` for the time methods; None for the band methods.
        rule (str): The rule sentence products record.
    """

    key: str
    engine: str
    label: str
    uses: tuple
    fields: tuple
    stack: str
    weighting: str | None
    rule: str


_BAND_RULE = ("per band, each member's calibrated channel divided by the square root of its median band power over "
              "the windows; in each window a member whose normalised power exceeds reject_factor times the median "
              "over the members present is left out, {combine}, and a window keeping fewer than min_members in "
              "either channel is left out of the band")
METHODS: dict[str, Method] = {
    "band_mean": Method(
        "band_mean", "band", "band mean", ("base", "reference"), ("E", "H"), "mean", None,
        _BAND_RULE.format(combine="the stack is the mean of the members kept")),
    "band_median": Method(
        "band_median", "band", "band median", ("base", "reference"), ("E", "H"), "median", None,
        _BAND_RULE.format(combine="the stack is the median of the real parts and the median of the imaginary "
                                  "parts of the members kept (with two kept, their mean)")),
    "time_mean": Method(
        "time_mean", "time", "time mean", ("remote",), ("H",), "mean", "none",
        "per coil, the plain mean of the members in 600 s chunks, offsets not removed; the stack carries the "
        "members' common filter chain, so a transfer function against it has errors in physical units"),
    "time_coherence": Method(
        "time_coherence", "time", "time coherence-weighted", ("remote",), ("H",), "mean", "coherence",
        "per coil and 600 s chunk, each member's median removed and the member weighted by its squared "
        "coherence over 0.1-10 s with the mean of the other members, normalised per chunk; a member under 0.05 "
        "in a chunk is dropped from it"),
}


def applicable_keys(method: str, use: str) -> tuple[str, ...]:
    """Return the recipe keys a method and use take, in the order a block holds them.

    ``exclude`` is listed for the band methods; `Recipe.from_mapping`
    refuses it beside a member list.

    Args:
        method (str): A key of `METHODS`.
        use (str): One of the method's `Method.uses`.

    Returns:
        tuple of str: Keys of `KEYS`.

    Raises:
        StacksError: For an unknown method, or a use the method does not take.
    """
    spec = METHODS.get(method)
    if spec is None:
        raise StacksError(f"unknown method {method!r} (known: {', '.join(METHODS)})")
    if use not in spec.uses:
        raise StacksError(f"method {method} takes use {' or '.join(spec.uses)}, not {use!r}")
    keys = KEYS
    if spec.engine == "time":
        keys = tuple(k for k in keys if k not in _BAND_ONLY)
    if use != "base":
        keys = tuple(k for k in keys if k not in _BASE_ONLY)
    return keys


def _error(name: str, key: str, message: str) -> StacksError:
    """Return a StacksError naming the recipe and the key."""
    return StacksError(f"{name}, {key}: {message}")


def _number(name: str, key: str, value, positive: bool = True) -> float:
    """Return a YAML number as a float; refuse booleans, text and non-finite values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise _error(name, key, f"a number, not {value!r}")
    if positive and value <= 0:
        raise _error(name, key, f"must be above 0, not {value!r}")
    return float(value)


def _names(name: str, key: str, value) -> tuple[str, ...]:
    """Return a list of site names sorted and unique; refuse anything else (a tuple is taken as a list)."""
    if not isinstance(value, (list, tuple)):
        raise _error(name, key, f"a list of site names, not {value!r}")
    for item in value:
        if not isinstance(item, str) or not item or item.strip() != item:
            raise _error(name, key, f"site names are text without spaces at either end, not {item!r} "
                                    f"(quote a name YAML would read as a number)")
    return tuple(sorted(set(value)))


def _time(name: str, key: str, value) -> pd.Timestamp:
    """Return a recipe time as a UTC Timestamp with zero seconds.

    Text (``YYYY-MM-DD HH:MM``) and YAML datetimes are taken; naive is UTC,
    a zone-aware time is converted to UTC.
    """
    if isinstance(value, str):
        if not _TIME_TEXT_RE.match(value.strip()):
            raise _error(name, key, f"write a UTC time as YYYY-MM-DD HH:MM, not {value!r}")
        value = value.strip()
    elif isinstance(value, bool) or not isinstance(value, (dt.datetime, dt.date)):
        raise _error(name, key, f"write a UTC time as YYYY-MM-DD HH:MM, not {value!r}")
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError) as exc:
        raise _error(name, key, f"not a time ({exc}): write YYYY-MM-DD HH:MM") from None
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    if ts.second or ts.microsecond or ts.nanosecond:
        raise _error(name, key, f"seconds must be 0 ({ts.isoformat()}): the file holds minutes only, so a "
                                f"re-save would change the recipe")
    return ts


def _choice(name: str, key: str, value, allowed: tuple) -> str:
    """Return a value of `allowed`; YAML's booleans get their own explanation."""
    if isinstance(value, bool):
        raise _error(name, key, f"{' or '.join(allowed)}, not {value} (YAML reads on, off, yes and no as "
                                f"true or false)")
    if value not in allowed:
        raise _error(name, key, f"{' or '.join(allowed)}, not {value!r}")
    return value


def check_name(name) -> str:
    """Return a recipe name, or raise when it is not one.

    Args:
        name (str): ``STK_`` then letters and digits in parts joined by
            single underscores, at most `NAME_MAX` characters.

    Returns:
        str: The name.

    Raises:
        StacksError: If it is not a recipe name.
    """
    if not isinstance(name, str) or not NAME_RE.match(name) or len(name) > NAME_MAX:
        raise StacksError(f"{name!r}: a recipe name is STK_ then letters and digits in parts joined by single "
                          f"underscores, at most {NAME_MAX} characters (for example STK_NADOR_H)")
    return name


@dataclass(frozen=True)
class Recipe:
    """One stack recipe, validated and with its defaults filled.

    Made through `from_mapping` only, which sorts and de-duplicates the
    lists, converts the times to UTC and fills the defaults, so two equal
    recipes are the same recipe and a loaded recipe equals the one saved.
    Keys that do not apply to the method and use are None (`exclude` is
    ``()``).

    Attributes:
        name (str): ``STK_...``.
        field (str): ``"H"`` (hx, hy) or ``"E"`` (ex, ey).
        use (str): ``"base"`` or ``"reference"`` (band methods),
            ``"remote"`` (time methods).
        method (str): A key of `METHODS`.
        sample_rate (float): Hz.
        members (tuple or None): Site names, sorted; None is the rule
            (never None for a time method).
        exclude (tuple): Sites the rule leaves out.
        min_overlap_hours (float or None): Band methods.
        start, end (pd.Timestamp or None): The window, UTC.
        reject_factor (float or None): Band methods.
        min_members (int or None): Band methods.
        screen_polarity (str or None): Band base stacks.
        member_change (str or None): Band base stacks.
        use_filters (bool): Whether the members are read through their
            filters (the run's own ``--no-filters`` must agree).
        notes (str): Free text, outside the hash.
    """

    name: str
    field: str
    use: str
    method: str
    sample_rate: float
    members: tuple[str, ...] | None
    exclude: tuple[str, ...] = ()
    min_overlap_hours: float | None = None
    start: pd.Timestamp | None = None
    end: pd.Timestamp | None = None
    reject_factor: float | None = None
    min_members: int | None = None
    screen_polarity: str | None = None
    member_change: str | None = None
    use_filters: bool = True
    notes: str = ""

    @property
    def roles(self) -> tuple[str, str]:
        """The channels the stack takes: ("hx", "hy") or ("ex", "ey")."""
        return intersite.FIELDS[self.field]

    @property
    def engine(self) -> str:
        """``"band"`` or ``"time"``."""
        return METHODS[self.method].engine

    @property
    def window_ns(self) -> tuple[int, int] | None:
        """The window as (start, end) ns since the epoch, or None when the recipe has none."""
        if self.start is None:
            return None
        return int(self.start.value), int(self.end.value)

    @classmethod
    def from_mapping(cls, name: str, mapping) -> "Recipe":
        """Return the recipe a stacks.yaml block declares.

        Args:
            name (str): The recipe name.
            mapping (dict): The block's keys and values, as YAML loads them.

        Returns:
            Recipe: Validated, defaults filled.

        Raises:
            StacksError: Naming the recipe and the key, for an unknown key, a
                key the method or use does not take, a missing required key,
                a value outside its range or a time_coherence window shorter
                than `COHERENCE_MIN_S`.
        """
        name = check_name(name)
        if not isinstance(mapping, dict):
            raise StacksError(f"{name}: a recipe is a mapping of keys, not {mapping!r}")
        for key in mapping:
            if key not in KEYS:
                raise _error(name, str(key), f"unknown key (known: {', '.join(KEYS)})")
        method = mapping.get("method", DEFAULT_METHOD)
        if not isinstance(method, str) or method not in METHODS:
            raise _error(name, "method", f"{' or '.join(METHODS)}, not {method!r}")
        spec = METHODS[method]
        if "field" not in mapping:
            raise _error(name, "field", "required: H (hx, hy) or E (ex, ey)")
        field = mapping["field"]
        if not isinstance(field, str) or field not in intersite.FIELDS:
            raise _error(name, "field", f"H (hx, hy) or E (ex, ey), not {field!r}")
        if field not in spec.fields:
            raise _error(name, "field", f"{method} stacks {' or '.join(spec.fields)} only (a time stack holds "
                                        f"hx and hy)")
        if spec.engine == "band" and "use" not in mapping:
            raise _error(name, "use", "required for a band method: base or reference")
        use = mapping.get("use", "remote")
        if not isinstance(use, str) or use not in spec.uses:
            raise _error(name, "use", f"{method} takes {' or '.join(spec.uses)}, not {use!r}")
        allowed = applicable_keys(method, use)
        for key in mapping:
            if key not in allowed:
                raise _error(name, key, f"does not apply to {method} with use {use} (it takes "
                                        f"{', '.join(allowed)})")
        if "sample_rate" not in mapping:
            raise _error(name, "sample_rate", "required, in Hz")
        sample_rate = _number(name, "sample_rate", mapping["sample_rate"])
        band = spec.engine == "band"
        raw = mapping.get("members", MEMBER_RULE if band else None)
        if raw is None:
            raise _error(name, "members", "required for a time method: a list of at least two sites")
        if raw == MEMBER_RULE:
            if not band:
                raise _error(name, "members", "a time recipe takes a list of sites, not rule: the archive must "
                                              "leave out the station it is later the remote of")
            members = None
        else:
            members = _names(name, "members", raw)
            if not band and len(members) < 2:
                raise _error(name, "members", f"a time recipe stacks at least two sites, not {list(members)}")
        exclude = ()
        if "exclude" in mapping:
            if members is not None:
                raise _error(name, "exclude", "applies with members: rule only; leave the site off the list")
            exclude = _names(name, "exclude", mapping["exclude"])
        if ("start" in mapping) != ("end" in mapping):
            missing = "end" if "start" in mapping else "start"
            raise _error(name, missing, "give start and end together, or neither")
        if not band and "start" not in mapping:
            raise _error(name, "start", "required for a time method, with end")
        start = end = None
        if "start" in mapping:
            start, end = _time(name, "start", mapping["start"]), _time(name, "end", mapping["end"])
            if end <= start:
                raise _error(name, "end", f"must come after start ({start:%Y-%m-%d %H:%M} UTC)")
            length_s = (end - start).total_seconds()
            if spec.weighting == "coherence" and length_s < COHERENCE_MIN_S:
                raise _error(name, "end", f"a {method} window spans at least {COHERENCE_MIN_S / 60:g} min "
                                          f"({COHERENCE_MIN_CHUNKS} coherence chunks of {WEIGHT_CHUNK_S:g} s); this "
                                          f"one spans {length_s / 60:g} min: widen it or use time_mean")
        use_filters = mapping.get("use_filters", True)
        if not isinstance(use_filters, bool):
            raise _error(name, "use_filters", f"true or false, not {use_filters!r}")
        if not band and not use_filters:
            raise _error(name, "use_filters", "a time recipe reads the members' processing archives (their "
                                              "filtered variants); false is not taken")
        notes = mapping.get("notes")
        if notes is None:
            notes = ""
        if not isinstance(notes, str):
            raise _error(name, "notes", f"text, not {notes!r} (quote it)")
        values = dict(name=name, field=field, use=use, method=method, sample_rate=sample_rate, members=members,
                      exclude=exclude, start=start, end=end, use_filters=use_filters, notes=notes)
        if band:
            values["min_overlap_hours"] = _number(name, "min_overlap_hours",
                                                  mapping.get("min_overlap_hours", intersite.MIN_OVERLAP_HOURS))
            factor = _number(name, "reject_factor", mapping.get("reject_factor", intersite.STACK_REJECT_FACTOR))
            if factor <= 1:
                raise _error(name, "reject_factor", f"must be above 1, not {factor:g}")
            values["reject_factor"] = factor
            least = mapping.get("min_members", intersite.STACK_MIN_MEMBERS)
            if isinstance(least, bool) or not isinstance(least, int) or least < 1:
                raise _error(name, "min_members", f"a whole number of 1 or more, not {least!r}")
            if members is not None and len(members) < least:
                raise _error(name, "members", f"the list names {len(members)} site(s), fewer than min_members "
                                              f"{least}")
            values["min_members"] = least
            if use == "base":
                values["screen_polarity"] = _choice(name, "screen_polarity",
                                                    mapping.get("screen_polarity", POLARITY[0]), POLARITY)
                values["member_change"] = _choice(name, "member_change",
                                                  mapping.get("member_change", MEMBER_CHANGE[0]), MEMBER_CHANGE)
        return cls(**values)

    def stored(self) -> dict:
        """Return the mapping a stacks.yaml block holds for this recipe.

        Keys in the order of `applicable_keys`, defaults written out;
        ``exclude`` only beside ``members: rule``, ``start`` and ``end``
        only when set (as ``YYYY-MM-DD HH:MM`` UTC text), ``notes`` only
        when not empty.
        """
        out = {}
        for key in applicable_keys(self.method, self.use):
            value = getattr(self, key)
            if key == "members":
                out[key] = MEMBER_RULE if value is None else list(value)
            elif key == "exclude":
                if self.members is None:
                    out[key] = list(value)
            elif key in ("start", "end"):
                if value is not None:
                    out[key] = value.strftime(TIME_FMT)
            elif key == "notes":
                if value:
                    out[key] = value
            else:
                out[key] = value
        return out

    def canonical(self) -> dict:
        """Return the recipe as the hash sees it.

        The keys of `applicable_keys` less ``notes``, with defaults filled:
        numbers through float() or int(), lists sorted and unique, times as
        ``YYYY-MM-DDTHH:MM:SSZ`` or None. The name is not part of it.
        """
        out = {}
        for key in applicable_keys(self.method, self.use):
            value = getattr(self, key)
            if key == "notes":
                continue
            if key == "members":
                out[key] = MEMBER_RULE if value is None else sorted(set(value))
            elif key == "exclude":
                out[key] = sorted(set(value))
            elif key in ("start", "end"):
                out[key] = None if value is None else value.strftime(CANONICAL_TIME_FMT)
            elif key in ("sample_rate", "min_overlap_hours", "reject_factor"):
                out[key] = float(value)
            elif key == "min_members":
                out[key] = int(value)
            elif key == "use_filters":
                out[key] = bool(value)
            else:
                out[key] = str(value)
        return out


def canonical_text(recipe: Recipe) -> str:
    """Return the canonical JSON text of a recipe, the text its hash is taken over.

    Args:
        recipe (Recipe): The recipe.

    Returns:
        str: ``json.dumps(recipe.canonical(), sort_keys=True,
        separators=(",", ":"), ensure_ascii=True)``.
    """
    return json.dumps(recipe.canonical(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def recipe_hash(recipe: Recipe) -> str:
    """Return the first 12 hex digits of the SHA-256 of the recipe's canonical text.

    Args:
        recipe (Recipe): The recipe.

    Returns:
        str: 12 lower-case hex digits.
    """
    return hashlib.sha256(canonical_text(recipe).encode("ascii")).hexdigest()[:12]


def rule_text(recipe: Recipe) -> str:
    """Return the recipe's stacking rule followed by its parameters, as the Stacks tab shows it.

    Args:
        recipe (Recipe): The recipe.

    Returns:
        str: For example "... (reject_factor 25, min_members 2, polarity
        drop, membership constant)".
    """
    rule = METHODS[recipe.method].rule
    if recipe.engine == "time":
        return rule
    params = [f"reject_factor {recipe.reject_factor:g}", f"min_members {recipe.min_members}"]
    if recipe.use == "base":
        params += [f"polarity {recipe.screen_polarity}", f"membership {recipe.member_change}"]
    return f"{rule} ({', '.join(params)})"


def provenance(recipe: Recipe) -> dict:
    """Return what a product made from a recipe records of it.

    Args:
        recipe (Recipe): The recipe.

    Returns:
        dict: ``recipe`` (the name), ``recipe_hash``, ``recipe_text`` (the
        canonical text) and ``rule`` (the method's rule sentence).
    """
    return {"recipe": recipe.name, "recipe_hash": recipe_hash(recipe), "recipe_text": canonical_text(recipe),
            "rule": METHODS[recipe.method].rule}


# --- the file -------------------------------------------------------------------------------------------------


def stacks_path(survey) -> Path:
    """Return the stacks.yaml path of a survey.

    Args:
        survey (Survey or str or Path): A `Survey`, a survey.yaml path or the
            survey folder.

    Returns:
        Path: ``<survey folder>/stacks.yaml``.
    """
    folder = getattr(survey, "config_dir", None)
    if folder is None:
        folder = Path(survey)
        if folder.suffix.lower() in (".yaml", ".yml"):
            folder = folder.parent
    return Path(folder) / STACKS_FILE


def _survey(survey):
    """Return a Survey for a Survey, a survey.yaml path or the survey folder."""
    if hasattr(survey, "site_names"):
        return survey
    from .survey import Survey

    path = Path(survey)
    return Survey.from_yaml(path if path.suffix.lower() in (".yaml", ".yml") else path / "survey.yaml")


class _Parse(NamedTuple):
    """One read of a stacks.yaml: its text, newline, byte-order mark, document and error."""

    text: str
    newline: str
    bom: bool
    document: dict | None
    error: str | None


class _Span(NamedTuple):
    """One block: its name, the index of its key line and of its last indented line."""

    name: str
    first: int
    last: int


def _is_blank(line: str) -> bool:
    return not line.strip()


def _is_content(line: str) -> bool:
    """Return whether a line belongs to the block above it: indented, or a column-0 sequence entry."""
    return not _is_blank(line) and (line[:1] in (" ", "\t") or line.startswith("- ") or line.rstrip("\r\n") == "-")


def _spans(lines: list[str], path=None) -> list[_Span]:
    """Return the blocks of a stacks.yaml's lines.

    A block is a column-0 key line, the indented lines below it and the
    blank lines between those; it ends at its last indented line. Column-0
    comment lines are never part of a block, including those between its
    indented lines. Every other line is text no save touches.

    Raises:
        StacksError: If two key lines carry one name (both line numbers are
            named).
    """
    spans, seen = [], {}
    i, n = 0, len(lines)
    while i < n:
        match = _KEY_LINE.match(lines[i]) if lines[i][:1] not in (" ", "\t", "#") else None
        if match is None:
            i += 1
            continue
        name = match.group("name").strip()
        if name in seen:
            raise StacksError(f"{path or STACKS_FILE}: {name} is declared twice, at lines {seen[name] + 1} and "
                              f"{i + 1}; remove or rename one (YAML would keep the last without a word)")
        seen[name] = i
        last, j = i, i + 1
        while j < n:
            line = lines[j]
            if _is_content(line):
                last = j
            elif not (_is_blank(line) or line.startswith("#")):
                break
            j += 1
        spans.append(_Span(name, i, last))
        i = last + 1
    return spans


def _newline(text: str) -> str:
    """Return the newline of a text's first line, "\\n" when it has none."""
    end = text.find("\n")
    return "\r\n" if end > 0 and text[end - 1] == "\r" else "\n"


def _parse(data: bytes, path=None) -> _Parse:
    """Parse a stacks.yaml's bytes; a file error goes into the result's `error`."""
    bom = data.startswith(_BOM)
    try:
        text = data[len(_BOM):].decode("utf-8") if bom else data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return _Parse("", "\n", bom, None, f"{path or STACKS_FILE}: not UTF-8 text ({exc})")
    newline = _newline(text)
    try:
        _spans(text.splitlines(keepends=True), path)
        document = yaml.load(text, Loader=_LOADER)
    except StacksError as exc:
        return _Parse(text, newline, bom, None, str(exc))
    except yaml.YAMLError as exc:
        return _Parse(text, newline, bom, None, f"{path or STACKS_FILE}: not YAML ({exc})")
    if document is None:
        document = {}
    if not isinstance(document, dict):
        return _Parse(text, newline, bom, None, f"{path or STACKS_FILE}: the file must be a mapping of recipe "
                                                f"names, not a {type(document).__name__}")
    unknown = [k for k in document if k != CHART_KEY and not (isinstance(k, str) and k.startswith("STK_"))]
    if unknown:
        return _Parse(text, newline, bom, None, f"{path or STACKS_FILE}: top-level key(s) {unknown} are neither "
                                                f"a recipe (STK_...) nor {CHART_KEY}")
    return _Parse(text, newline, bom, document, None)


def _read(path: Path) -> _Parse:
    """Return a stacks.yaml parsed, parsing it only when it changed since the last parse.

    The parse is kept per path with the file's (st_mtime_ns, st_size),
    taken before the read; a file modified within `RACY_S` of its read is
    read again next time and parsed if its bytes differ (the rule of
    `mt_workbench.masks.read_document`).

    Raises:
        OSError: If the file cannot be read.
    """
    key = os.path.abspath(path)
    with _LOCK:
        now = time.time_ns()
        status = path.stat()
        stamp = (status.st_mtime_ns, status.st_size)
        kept = _PARSED.get(key)
        if kept is None or kept[0] != stamp or kept[1] is not None:
            data = path.read_bytes()
            if kept is not None and kept[0] == stamp and kept[1] == data:
                parse = kept[2]
            else:
                parse = _parse(data, path)
            racy = stamp[0] + int(RACY_S * 1e9) >= now  # modified too recently to trust the stamp alone
            kept = _PARSED[key] = (stamp, data if racy else None, parse)
    return kept[2]


def _document(path: Path) -> dict:
    """Return a stacks.yaml's document, {} with no file; raise StacksError for a file error."""
    if not path.exists():
        return {}
    parse = _read(path)
    if parse.error:
        raise StacksError(parse.error)
    return parse.document


def _replace_bytes(path: Path, data: bytes) -> None:
    """Write bytes to a file atomically: a temporary file in its folder, then `os.replace`.

    On Windows `os.replace` fails while another process holds the target
    open, so it is tried `REPLACE_TRIES` times, 0.1 s apart; the temporary
    file is removed when it cannot be moved.
    """
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_bytes(data)
        for attempt in range(REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == REPLACE_TRIES - 1:
                    raise
                time.sleep(0.1)
    finally:
        if tmp.exists():
            tmp.unlink()
        with _LOCK:
            _PARSED.pop(os.path.abspath(path), None)  # the next read parses the new bytes


def _with_block(text: str, name: str, block: str, newline: str) -> str:
    """Return the text with the named block replaced by `block`, or with `block` appended.

    The block's key line and indented lines (and the blank lines between
    them) go; a column-0 comment line found between them is kept and placed
    just below the new block. A new name goes at the end, after one blank
    line.
    """
    lines = text.splitlines(keepends=True)
    for span in _spans(lines):
        if span.name == name:
            moved = [line for line in lines[span.first: span.last + 1] if line.startswith("#")]
            return "".join(lines[: span.first]) + block + "".join(moved) + "".join(lines[span.last + 1:])
    out = text
    if out and not out.endswith(("\n", "\r")):
        out += newline
    if out and lines and not _is_blank(lines[-1]):
        out += newline
    return out + block


def _write_block(path: Path, name: str, value: dict) -> None:
    """Replace or add one top-level block of a stacks.yaml, carrying every other byte over.

    The new text is parsed before the write, and the write happens only if
    the block reads back as `value`.

    Raises:
        StacksError: If the present file has a file error.
    """
    data = path.read_bytes() if path.exists() else b""
    if data:
        parse = _parse(data, path)
        if parse.error:
            raise StacksError(f"{parse.error}; fix stacks.yaml by hand before saving from the GUI")
        text, newline, bom = parse.text, parse.newline, parse.bom
    else:
        text, newline, bom = HEADER, "\n", False
    block = yaml.dump({name: value}, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                      default_flow_style=False, width=100)
    out = _with_block(text, name, block.replace("\n", newline), newline)
    check = _parse(out.encode("utf-8"), path)
    if check.error or check.document.get(name) != value:
        raise StacksError(f"{path}: the new {name} block does not read back as written "
                          f"({check.error or check.document.get(name)}); nothing was written")
    _replace_bytes(path, (_BOM if bom else b"") + out.encode("utf-8"))


def load_recipes(survey) -> tuple[dict[str, Recipe], dict[str, str]]:
    """Load every recipe of a survey's stacks.yaml.

    The file is parsed once per change (`_read`). One invalid recipe does
    not hide the others.

    Args:
        survey (Survey or str or Path): A `Survey`, a survey.yaml path or the
            survey folder.

    Returns:
        tuple: (the valid recipes by name, the error text of each invalid
        recipe by name), each in file order; ({}, {}) with no file.

    Raises:
        StacksError: For a file error: text that is not YAML or not a
            mapping, a top-level key that is neither ``STK_...`` nor
            ``chart``, or two key lines with one name.
        OSError: If the file exists and cannot be read.
    """
    document = _document(stacks_path(survey))
    valid, errors = {}, {}
    for key, value in document.items():
        if key == CHART_KEY:
            continue
        try:
            valid[key] = Recipe.from_mapping(key, value)
        except StacksError as exc:
            errors[key] = str(exc)
    return valid, errors


def load_recipe(survey, name: str) -> Recipe:
    """Load one recipe of a survey's stacks.yaml.

    Args:
        survey (Survey or str or Path): A `Survey`, a survey.yaml path or the
            survey folder.
        name (str): The recipe name.

    Returns:
        Recipe: The recipe.

    Raises:
        StacksError: For a file error, a name the file does not hold (the
            names it holds are listed) or an invalid recipe.
    """
    valid, errors = load_recipes(survey)
    if name in valid:
        return valid[name]
    if name in errors:
        raise StacksError(errors[name])
    names = sorted(valid) + sorted(errors)
    raise StacksError(f"{name}: no such recipe in {stacks_path(survey)} (it holds: "
                      f"{', '.join(names) if names else 'none'})")


def save_recipe(survey, recipe: Recipe) -> Path:
    """Write one recipe to the survey's stacks.yaml.

    The recipe's block (its key line and indented lines) is replaced, or
    added at the end; every other byte of the file is carried over, and the
    file keeps its newline (and a UTF-8 byte-order mark it starts with). A
    new file starts with `HEADER`. The survey is not reopened. A name equal
    to a raw data folder is not refused here, since that needs a listing of
    `data_root`, which may sit on a drive not plugged in and took 1.9 s on
    the Atlas survey while masks.yaml was parsed [measured, fix round]: the Stacks tab checks
    it against `State.raw_sites` before it saves, and build_stack.py against
    `Survey.site_dirs` before it builds (design 9, the name row).

    Args:
        survey (Survey or str or Path): The survey; a path is read as its
            survey.yaml.
        recipe (Recipe): Made by `Recipe.from_mapping`.

    Returns:
        Path: stacks.yaml.

    Raises:
        StacksError: If the recipe does not read back from its own stored
            form, its name is a site of survey.yaml, or the present file
            has a file error.
    """
    survey = _survey(survey)
    if not isinstance(recipe, Recipe):
        raise TypeError(f"save_recipe takes a Recipe, not {type(recipe).__name__}")
    if Recipe.from_mapping(recipe.name, recipe.stored()) != recipe:
        raise StacksError(f"{recipe.name}: the recipe does not read back from its stored form; make it with "
                          f"Recipe.from_mapping")
    if recipe.name in survey.site_names():
        raise StacksError(f"{recipe.name}: survey.yaml has a site of this name; choose another name")
    path = stacks_path(survey)
    _write_block(path, recipe.name, recipe.stored())
    logger.info(f"saved stack recipe {recipe.name} ({recipe.method}, recipe hash {recipe_hash(recipe)}) to {path}")
    return path


def _check_night(night) -> str:
    """Return a night window "HH:MM-HH:MM", or raise StacksError."""
    if not isinstance(night, str) or not _NIGHT_RE.match(night):
        raise _error(CHART_KEY, "night", f"HH:MM-HH:MM in local time (an end before the start runs past "
                                         f"midnight), not {night!r}")
    if night[:5] == night[6:]:
        raise _error(CHART_KEY, "night", f"start and end are equal: {night}")
    return night


def _default_references(survey) -> list[str]:
    """Return the sites survey.yaml names as a remote: of any site, observatories left out, sorted."""
    from .survey import OBSERVATORY

    entries = survey.config.get("sites") or {}
    default = survey.defaults.get("remote")
    names = set(survey.site_names())
    out = set()
    for site in names:
        remote = (entries.get(site) or {}).get("remote", default)
        if remote and remote in names and (entries.get(remote) or {}).get("instrument") != OBSERVATORY:
            out.add(remote)
    return sorted(out)


def load_chart(survey) -> dict:
    """Return the Stacks tab's chart settings, defaults filled.

    Args:
        survey (Survey or str or Path): The survey; a path is read as its
            survey.yaml (the default references come from it).

    Returns:
        dict: ``references`` (list of site names; by default the sites
        survey.yaml names as a ``remote:``, observatories left out) and
        ``night`` ("HH:MM-HH:MM" local time in survey.timezone; by default
        `DEFAULT_NIGHT`).

    Raises:
        StacksError: For a file error or an invalid chart block.
    """
    survey = _survey(survey)
    block = _document(stacks_path(survey)).get(CHART_KEY)
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise StacksError(f"{CHART_KEY}: a mapping of {' and '.join(CHART_KEYS)}, not {block!r}")
    for key in block:
        if key not in CHART_KEYS:
            raise _error(CHART_KEY, str(key), f"unknown key (known: {', '.join(CHART_KEYS)})")
    if "references" in block:
        given = block["references"] or []
        _names(CHART_KEY, "references", given)  # checks only: the order is the chart's group order
        references = list(dict.fromkeys(given))
    else:
        references = _default_references(survey)
    return {"references": references, "night": _check_night(block.get("night", DEFAULT_NIGHT))}


def save_chart(survey, references, night: str) -> Path:
    """Write the chart block of the survey's stacks.yaml.

    Args:
        survey (Survey or str or Path): The survey.
        references (list of str): The reference sites, in the order the
            chart groups by them (repeats dropped).
        night (str): "HH:MM-HH:MM", local time in survey.timezone.

    Returns:
        Path: stacks.yaml.

    Raises:
        StacksError: For a bad reference list or night, or a file error.
    """
    if isinstance(references, str):
        raise _error(CHART_KEY, "references", f"a list of site names, not the text {references!r}")
    references = list(references)
    _names(CHART_KEY, "references", references)
    value = {"references": list(dict.fromkeys(references)), "night": _check_night(night)}
    path = stacks_path(survey)
    _write_block(path, CHART_KEY, value)
    logger.info(f"saved the Stacks chart settings to {path}")
    return path


# --- members and command lines --------------------------------------------------------------------------------


def best_run(runs, lo_ns: int, hi_ns: int) -> list[tuple[int, int]]:
    """Return the one run that overlaps [lo_ns, hi_ns) most, as `mt_workbench.virtual` builds from it.

    Args:
        runs (list): (start_ns, end_ns) per run.
        lo_ns, hi_ns (int): The window, ns since the epoch.

    Returns:
        list: A one-item list holding that run; the earlier run on a tie
        (virtual keeps the first maximum); [] when no run overlaps.
    """
    best, most = None, 0
    for start, end in sorted(runs):
        overlap = min(end, hi_ns) - max(start, lo_ns)
        if overlap > most:
            best, most = (start, end), overlap
    return [] if best is None else [best]


def _ns(value) -> int:
    """Return ns since the epoch for an int or a time (naive is UTC)."""
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return int(value)
    ts = pd.Timestamp(value)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return int(ts.value)


def resolve_members(recipe: Recipe, survey, window=None, local: str | None = None, base: str | None = None,
                    runs_of: Callable | None = None, min_overlap_hours: float | None = None,
                    edge_s: float | None = None) -> tuple[list[dict], list[dict]]:
    """Return a recipe's members over a window, and the sites left out with their reasons.

    Calls `mt_workbench.intersite.select_stack` at the recipe's rate. The
    rule leaves out the recipe's ``exclude``; a list leaves out every other
    site of survey.yaml with the reason `NOT_LISTED` (the local and the base
    keep their own reasons), and a listed name with no survey.yaml entry is
    added with `NO_ENTRY`. A time recipe's site is judged by its single run
    that overlaps the window most (`best_run`), as virtual builds it.

    Args:
        recipe (Recipe): The recipe.
        survey (Survey or str or Path): The survey.
        window (tuple or None): (start, end) as ns since the epoch or times;
            None for the recipe's.
        local (str or None): The local site (band methods).
        base (str or None): The base site (band reference recipes).
        runs_of (callable or None): ``runs_of(site, path, roles)`` giving a
            site's runs, or None for a site not read yet; with it no file is
            opened. None reads each archive's run list with h5py.
        min_overlap_hours (float or None): Overlap a member needs; None
            for the recipe's (band methods) or the window less
            `mt_workbench.intersite.MEMBER_EDGE_S` (time methods). The
            Stacks chart passes 0.0 to get every candidate.
        edge_s (float or None): Passed to `select_stack`: seconds a member
            may start late or end early when the window is shorter than the
            overlap a member needs. None asks for the whole window less one
            sample period.

    Returns:
        tuple: (members, left_out) as `select_stack` gives them: ``site``
        and ``overlap_h`` per member, ``site`` and ``reason`` per site
        left out.

    Raises:
        StacksError: With no window; for a local or base at another rate
            than the recipe's; for a local or base given to a time recipe,
            or a base given to a base recipe.
    """
    survey = _survey(survey)
    if window is None:
        window = recipe.window_ns
        if window is None:
            raise StacksError(f"{recipe.name}: the recipe declares no window and none was given")
    lo, hi = _ns(window[0]), _ns(window[1])
    if hi <= lo:
        raise StacksError(f"{recipe.name}: the window ends before it starts")
    time_method = recipe.engine == "time"
    if time_method and (local is not None or base is not None):
        raise StacksError(f"{recipe.name}: a time recipe takes no local or base site: its archive is the same "
                          f"for every local")
    if recipe.use == "base" and base is not None:
        raise StacksError(f"{recipe.name}: a base recipe is the base; it takes no base site")
    for role, site in (("local", local), ("base", base)):
        if site is not None and not math.isclose(survey.sample_rate_of(site), recipe.sample_rate, rel_tol=1e-9):
            raise StacksError(f"{recipe.name}: the {role} {site} is at {survey.sample_rate_of(site):g} Hz, the "
                              f"recipe at {recipe.sample_rate:g} Hz")
    sites = survey.site_names()
    unlisted = set() if recipe.members is None else {s for s in sites if s not in recipe.members}
    exclude = sorted(set(recipe.exclude) | unlisted)
    if min_overlap_hours is not None:
        need = float(min_overlap_hours)
    elif time_method:
        need = max(0.0, (hi - lo) / 3.6e12 - intersite.MEMBER_EDGE_S / 3600.0)
    else:
        need = recipe.min_overlap_hours
    runs = runs_of
    if time_method:
        def runs(site, path, roles):
            got = runs_of(site, path, roles) if runs_of is not None else intersite.archive_runs(path, site, roles)
            return None if got is None else best_run(got, lo, hi)
    members, left_out = intersite.select_stack(survey, local, base, lo, hi, recipe.roles, exclude, need,
                                               rate=recipe.sample_rate, runs_of=runs, edge_s=edge_s)
    for item in left_out:
        if item["site"] in unlisted and item["site"] not in (local, base):
            item["reason"] = NOT_LISTED
    if recipe.members is not None:
        known = set(sites)
        left_out.extend({"site": s, "reason": NO_ENTRY} for s in recipe.members if s not in known)
    return members, left_out


def _text(value, what: str) -> str:
    """Return a path or text argument as text; refuse other types."""
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    if not isinstance(value, str):
        raise TypeError(f"{what} must be text, not {type(value).__name__}")
    return value


def intersite_argv(python_exe, script, survey_yaml, local: str, kind: str, stacks, base: str | None = None,
                   remote: str | None = None, start: str | None = None, end: str | None = None,
                   tag: str | None = None, no_filters: bool = False, dry_run: bool = False) -> list[str]:
    """Return the scripts/process_intersite.py command line for recipe stacks.

    Only the types are checked; the script refuses bad combinations.

    Args:
        python_exe, script, survey_yaml (str or Path): The interpreter, the
            script and the survey.yaml.
        local (str): The local site.
        kind (str): ``telluric`` or ``magnetic``.
        stacks (list of str): Recipe names, one ``--stack`` each.
        base (str or None): The base site (with a reference recipe).
        remote (str or None): ``--remote`` (with a base recipe).
        start, end (str or None): The window, ``YYYY-MM-DD HH:MM`` UTC;
            both or neither.
        tag (str or None): ``--tag``.
        no_filters (bool): ``--no-filters``.
        dry_run (bool): ``--dry-run``.

    Returns:
        list of str: ``[python_exe, script, survey_yaml, local, (base),
        (start, end), --kind, kind, (--remote, remote), --stack, NAME ...,
        (--tag, tag), (--no-filters), (--dry-run)]``.

    Raises:
        TypeError: For an argument of the wrong type, or `stacks` given as
            one text.
        ValueError: For start without end or end without start.
    """
    if isinstance(stacks, (str, bytes)):
        raise TypeError("stacks is a list of recipe names, not one text")
    names = [_text(name, "a recipe name") for name in stacks]
    if (start is None) != (end is None):
        raise ValueError("give start and end together, or neither")
    argv = [_text(python_exe, "python_exe"), _text(script, "script"), _text(survey_yaml, "survey_yaml"),
            _text(local, "local")]
    if base is not None:
        argv.append(_text(base, "base"))
    if start is not None:
        argv += [_text(start, "start"), _text(end, "end")]
    argv += ["--kind", _text(kind, "kind")]
    if remote is not None:
        argv += ["--remote", _text(remote, "remote")]
    for name in names:
        argv += ["--stack", name]
    if tag is not None:
        argv += ["--tag", _text(tag, "tag")]
    if no_filters:
        argv.append("--no-filters")
    if dry_run:
        argv.append("--dry-run")
    return argv


def build_argv(python_exe, script, survey_yaml, name: str, overwrite: bool = True, check: bool = False) -> list[str]:
    """Return the scripts/build_stack.py command line for a time recipe.

    Args:
        python_exe, script, survey_yaml (str or Path): The interpreter, the
            script and the survey.yaml.
        name (str): The recipe name.
        overwrite (bool): ``--overwrite``; the GUI always passes it (an
            archive of the same recipe from the same member archives is
            still reused).
        check (bool): ``--check``.

    Returns:
        list of str: ``[python_exe, script, survey_yaml, --recipe, NAME,
        (--overwrite), (--check)]``.
    """
    argv = [_text(python_exe, "python_exe"), _text(script, "script"), _text(survey_yaml, "survey_yaml"),
            "--recipe", _text(name, "name")]
    if overwrite:
        argv.append("--overwrite")
    if check:
        argv.append("--check")
    return argv
