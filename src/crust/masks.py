# -*- coding: utf-8 -*-
"""
Time masks declared per site in `<survey>/masks.yaml`

A mask is an interval that processing leaves out. The file is written by the
"Save masks" button on the GUI Cross-powers tab and holds, per site, a list:

    C23:
    - start: '2023-09-22T12:05:49Z'   # UTC, ISO
      end: '2023-09-22T12:25:49Z'
      bands: all                      # or [pmin_s, pmax_s]
      reason: mains switching         # free text
      found_by: time                  # time | polar | cluster | night | gate: how it was found
      scope: local                    # local | both | remote: the roles of a pair it applies in
      channels: [ex]                  # optional: the channels the noise is on; every channel without it

`load_masks(survey, site)` and `save_masks(survey, site, masks)` read and
write one site's block. Saving rewrites that site's block of the file's text
and carries the other blocks and the leading comment over unchanged; the
text goes to a temporary file in the same folder and `os.replace` moves it
into place, so a reader never sees a part-written file.
`apply_time_masks(kd, masks)` cuts the masked intervals out of an aurora
KernelDataset. `applies(mask, period_s)` decides which bands a mask covers;
the Cross-powers tab, `crust.crosspower.masked_chunks` and
`crust.crosspower.stack_impedance` all use it.

A mask's `scope` says in which role of a remote-referenced pair it applies.
`local`, the default for an entry without the key, applies when its site is
the local of the pair; `both` applies when its site is the local and when it
is the remote; `remote` applies only when its site is the remote, for noise
that matters to the pairs using the site as their reference and not to the
site's own estimate. `masks_for_role(masks, role)` gives the masks of one
site that apply in a role, and `remote_masks` those of a pair's remote.

A mask's `channels` names the channels the noise is on, drawn from
`CHANNELS`; without the key it is on every channel (`"all"` after
`normalise`, and the key is written only as a list). An entry naming hx or
hy, or every channel, leaves out whole STFT windows (`cuts_whole_window`):
in the local role for every output row, in the remote role as a remote's
reference windows. An entry naming only output channels (ex, ey, hz)
applies in the local role to those rows of the transfer function alone
(`masks_for_row`), and not at all in the remote role, where the remote
contributes its hx and hy only (`remote_channel_split`).

Masks in processing: scripts/process_rr.py takes the masks of the local
site of scope local or both, and the masks of the remote site of scope both
or remote that name hx, hy or every channel (`remote_masks`; a stacked
remote named `STK_...` has none), joins them with `union_masks`, groups
them by output row (row r takes the whole-window entries and the entries
naming r), and passes each distinct group to
`crust.process.process_station(time_masks=...)` in a run of its own, then
merges the rows into one transfer function. Its `--mask-scope union` takes
every mask of both sites, whatever its scope. `process_station` calls
`apply_time_masks` with the masks whose `bands`
is `all`, which splits each run interval around them so aurora receives none
of those samples. A band-limited mask (`bands: [pmin_s, pmax_s]`, recorded by
a selection on the polar panel of the Cross-powers tab) reaches aurora
through a scoped runtime patch: `crust.process._band_masks_applied` drops
the STFT windows the mask overlaps (`windows_in_mask`) from each band whose
centre period it covers (`applies`), before the regression. Aurora 0.6.2 has
no input for this (docs/upstream_issues.md 22):

- `DecimationLevel.channel_weight_specs[].weights` is the only weight a
  config carries, and `aurora.pipelines.feature_weights.calculate_weights`
  overwrites it (``chws.weights = weights``, None when the spec has no
  feature weight specs) just before the regression;
- the regression then uses it as ``band_weights = weights.mean(axis=1)``
  (`aurora.pipelines.transfer_function_helpers.
  process_transfer_functions_with_weights`), one weight per STFT window,
  the same for every band of the level; the per-band lookup
  (``chws.get_weights_for_band(band)``) is commented out there;
- `process_mth5_legacy` builds the merged STFT objects and passes them
  straight to the regression with no callback between, and the mth5 method
  `apply_masks_and_weights` is an empty stub.

`crust.crosspower.stack_impedance`, the classical stacked remote-reference
estimate from the cross-powers of the kept chunks, also applies band masks,
and the masks naming only ex or ey to their own row.

Entries taken out of use are kept in `masks_history.yaml` beside masks.yaml
(`history_path`), in the same per-site block format, each with the keys it
had and ``retired: {on: 'YYYY-MM-DD', why: text}``. `retire_masks` moves the
entries a selection picks from a site's masks.yaml block to the end of its
history block, `restore_masks` moves them back without the `retired` key,
and `load_history` reads a site's history block; scripts/retire_masks.py is
the command line for the two.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

MASKS_FILE = "masks.yaml"
HISTORY_FILE = "masks_history.yaml"
MIN_PIECE_S = 600.0  # a run piece a mask leaves shorter than this is dropped
FOUND_BY = ("time", "polar", "cluster", "night", "gate")
# a mask applies to its site as the local; as the local and the remote; or as the remote alone
SCOPES = ("local", "both", "remote")
ROLES = ("local", "remote")       # the roles of a site in a remote-referenced pair
SCOPE_RULES = ("role", "union")   # role: by each mask's scope; union: every mask in both roles
SCOPES_OF_ROLE = {"local": ("local", "both"), "remote": ("both", "remote")}
CHANNELS = ("ex", "ey", "hx", "hy", "hz")  # the names a mask's `channels` may hold
WHOLE_WINDOW = ("hx", "hy")       # the TF inputs and the remote's reference channels
OUTPUTS = ("ex", "ey", "hz")      # the TF output rows, aurora's default order
HEADER = (
    "# Time masks declared on the GUI's Cross-powers tab (crust.masks): per site, the\n"
    "# intervals processing leaves out. bands: all (cut in time), or [pmin_s, pmax_s] (left\n"
    "# out of the bands whose centre period lies inside; see crust.masks). Times are UTC.\n"
    "# scope: local (the default) applies when the site is the local of a pair, both also\n"
    "# when it is the remote, remote only when it is the remote. channels (optional, every\n"
    "# channel without it): an entry naming only ex, ey or hz leaves out those TF rows alone.\n"
)
HISTORY_HEADER = (
    "# Masks taken out of use (crust.masks.retire_masks, scripts/retire_masks.py): per site,\n"
    "# the masks.yaml entries as they were, each with retired: {on: date, why: text}.\n"
    "# scripts/retire_masks.py --restore moves an entry back into masks.yaml.\n"
)
REPLACE_TRIES = 20  # os.replace attempts while a reader holds the file open (Windows)


class _Dumper(yaml.SafeDumper):
    """YAML dumper in block style that writes a list of plain numbers or names on one line.

    A mask's bands are written as ``[0.02, 0.1]`` and its channels as ``[ex]``.
    """


_Dumper.add_representer(
    list, lambda dumper, data: dumper.represent_sequence(
        "tag:yaml.org,2002:seq", data,
        flow_style=all(isinstance(v, (int, float, str)) and not isinstance(v, bool) for v in data) and bool(data)))


def masks_path(survey) -> Path:
    """Return the masks.yaml path of a survey.

    Args:
        survey (Survey or str or Path): A `Survey`, a survey.yaml path or the
            survey folder.

    Returns:
        Path: ``<survey folder>/masks.yaml``.
    """
    folder = getattr(survey, "config_dir", None)
    if folder is None:
        folder = Path(survey)
        if folder.suffix.lower() in (".yaml", ".yml"):
            folder = folder.parent
    return Path(folder) / MASKS_FILE


def utc(value) -> pd.Timestamp:
    """Return a UTC-aware Timestamp; naive input is taken as UTC."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def iso(value) -> str:
    """Format a time as ISO UTC, for example '2023-09-22T12:05:49Z'.

    Fractions of a second are kept when present.
    """
    return utc(value).isoformat().replace("+00:00", "Z")


def _channels(value):
    """Return a mask's channels as "all" or a sorted list of names from `CHANNELS`.

    Raises:
        ValueError: If the value is not "all", None or a non-empty list of
            names from `CHANNELS`.
    """
    if value is None or value == "all":
        return "all"
    if isinstance(value, (str, bytes)) or not hasattr(value, "__iter__"):
        raise ValueError(f"mask channels must be a list drawn from {CHANNELS}, not {value!r}")
    names = sorted({str(c).strip().lower() for c in value})
    if not names or any(n not in CHANNELS for n in names):
        raise ValueError(f"mask channels must be a non-empty list drawn from {CHANNELS}, not {value!r}")
    return names


def normalise(mask: dict) -> dict:
    """Check one mask and return it with its keys in the file's order.

    Args:
        mask (dict): Mask with ``start`` and ``end`` and optional ``bands``,
            ``reason``, ``found_by``, ``scope`` and ``channels``.

    Returns:
        dict: ``{"start", "end", "bands", "reason", "found_by", "scope",
        "channels"}``, times as ISO UTC text, ``bands`` as ``"all"`` or a
        sorted ``[pmin_s, pmax_s]``, ``scope`` ``"local"`` when the mask has
        none, ``channels`` ``"all"`` when it has none, else a sorted list.
        Other keys (``retired`` of a history entry) are left out.

    Raises:
        ValueError: If start or end is missing or unparseable, end is not
            after start, bands is malformed, found_by is not one of
            `FOUND_BY`, scope is not one of `SCOPES`, or channels is not a
            list drawn from `CHANNELS`.
    """
    try:
        start, end = utc(mask["start"]), utc(mask["end"])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"a mask needs a UTC start and end: {mask!r} ({exc})") from None
    if end <= start:
        raise ValueError(f"mask end {end} is not after its start {start}")
    bands = mask.get("bands", "all")
    if bands != "all":
        try:
            lo, hi = sorted(float(b) for b in bands)
        except (TypeError, ValueError):
            raise ValueError(f"mask bands must be 'all' or [pmin_s, pmax_s], not {bands!r}") from None
        bands = [lo, hi]
    found_by = str(mask.get("found_by", "time"))
    if found_by not in FOUND_BY:
        raise ValueError(f"mask found_by must be one of {FOUND_BY}, not {found_by!r}")
    scope = str(mask.get("scope", "local"))
    if scope not in SCOPES:
        raise ValueError(f"mask scope must be one of {SCOPES}, not {scope!r}")
    return {"start": iso(start), "end": iso(end), "bands": bands,
            "reason": str(mask.get("reason") or ""), "found_by": found_by, "scope": scope,
            "channels": _channels(mask.get("channels", "all"))}


def stored(mask: dict) -> dict:
    """Return a mask as masks.yaml holds it: normalised, ``channels`` written only as a list.

    An entry on every channel is written with the six keys it had before
    `channels` existed, so its block dumps byte for byte as it did. A
    ``retired`` record (a history entry) is kept, last.
    """
    out = normalise(mask)
    if out["channels"] == "all":
        del out["channels"]
    if mask.get("retired") is not None:
        out["retired"] = _retired(mask["retired"])
    return out


def _ordered(masks) -> list[dict]:
    """Normalise masks, sort them earliest first and collapse duplicates.

    A mask with the same interval, bands and channels as an earlier one, for
    example from a repeated click on the Cross-powers tab, is kept once.
    """
    out, seen = [], set()
    for m in sorted((normalise(m) for m in masks), key=lambda m: m["start"]):
        key = (m["start"], m["end"], str(m["bands"]), str(m["channels"]))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def load_masks(survey, site: str) -> list[dict]:
    """Load the masks of one site from masks.yaml.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.

    Returns:
        list of dict: Normalised masks, earliest first, duplicates
        collapsed. Empty when there is no file or no entry for the site.
    """
    path = masks_path(survey)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _ordered(data.get(site) or [])


def _blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Split masks.yaml text into its header and per-site blocks.

    A block runs from its unindented key line to the next one, including the
    comments and blank lines after it.

    Returns:
        tuple: ``(header, [(site, block_text), ...])``, where the header is
        the text before the first site.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines)
              if line[:1] not in ("", " ", "\t", "#", "-", "\n", "\r") and ":" in line]
    header = "".join(lines[: starts[0]]) if starts else text
    blocks = []
    for k, i in enumerate(starts):
        chunk = "".join(lines[i: starts[k + 1] if k + 1 < len(starts) else len(lines)])
        key = next(iter(yaml.safe_load(chunk) or {None: None}))
        blocks.append((str(key), chunk))
    return header, blocks


def replace_text(path, text: str) -> Path:
    """Write text to a file atomically: to a temporary file in its folder, then `os.replace`.

    A reader of `path` (a campaign runner reads masks.yaml at every job
    start) sees the old file or the new one, never a part-written one. The
    text is written as `Path.write_text` writes it. On Windows `os.replace`
    fails while another process holds the target open, so it is tried
    `REPLACE_TRIES` times, 0.1 s apart; the temporary file is removed when
    it cannot be moved.

    Args:
        path (str or Path): The file to write.
        text (str): Its new content.

    Returns:
        Path: `path`.
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
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
    return path


def _write_block(path: Path, header: str, site: str, entries: list[dict], keep_empty: bool = False) -> None:
    """Replace one site's block of a masks file with `entries` (already `stored`), atomically.

    The other sites' blocks and the leading comment are carried over as
    text, unchanged; a new file starts with `header`. An empty list removes
    the site's block, or writes ``<site>: []`` with `keep_empty`.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else header
    head, blocks = _blocks(text)
    new = (yaml.dump({site: entries}, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=100) if entries or keep_empty else "")
    out, placed = [], False
    for key, chunk in blocks:
        if key == site:
            out.append(new)
            placed = True
        else:
            out.append(chunk if chunk.endswith("\n") else chunk + "\n")
    if not placed and new:
        out.append(new)
    if head and not head.endswith("\n"):
        head += "\n"
    replace_text(path, head + "".join(out))


def save_masks(survey, site: str, masks, keep_empty: bool = False) -> Path:
    """Write the masks of one site to masks.yaml.

    The masks are normalised, sorted earliest first and collapsed as in
    `load_masks`, and written as `stored` gives them (``channels`` only as
    a list). The site's block is replaced; the other sites' blocks and the
    leading comment are carried over as text, unchanged. A new file starts
    with `HEADER`. The file is replaced atomically (`replace_text`).

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.
        masks (iterable of dict): The site's masks. An empty list removes
            the site's block, or leaves ``<site>: []`` with `keep_empty`.
        keep_empty (bool): Keep an emptied site's key, as `retire_masks` does.

    Returns:
        Path: The masks.yaml path.
    """
    path = masks_path(survey)
    entries = [stored(m) for m in _ordered(masks)]
    _write_block(path, HEADER, site, entries, keep_empty)
    logger.info(f"{site}: {len(entries)} mask(s) written to {path}")
    return path


def history_path(survey) -> Path:
    """Return the masks_history.yaml path of a survey, beside its masks.yaml.

    Args:
        survey (Survey or str or Path): A `Survey`, a survey.yaml path or the
            survey folder.

    Returns:
        Path: ``<survey folder>/masks_history.yaml``.
    """
    return masks_path(survey).with_name(HISTORY_FILE)


def _retired(value) -> dict:
    """Check a history entry's ``retired`` record and return ``{"on": 'YYYY-MM-DD', "why": text}``.

    Raises:
        ValueError: If it is not a mapping with a date ``on`` and a
            non-empty ``why``.
    """
    if not isinstance(value, dict):
        raise ValueError(f"a history entry's retired must be {{on: date, why: text}}, not {value!r}")
    # YAML 1.1 reads an unquoted key `on` as True; the dumper quotes it, a hand edit may not
    day = value.get("on", value.get(True))
    try:
        on = pd.Timestamp(str(day)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        raise ValueError(f"a history entry's retired.on must be a date, not {day!r}") from None
    why = str(value.get("why") or "").strip()
    if not why:
        raise ValueError("a history entry's retired.why must say why it was taken out of use")
    return {"on": on, "why": why}


def load_history(survey, site: str) -> list[dict]:
    """Load the history entries of one site from masks_history.yaml.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.

    Returns:
        list of dict: The entries in the file's order (the order they were
        retired), each normalised with its ``retired`` record; empty when
        there is no file or no block for the site.

    Raises:
        ValueError: If an entry does not normalise or has no valid
            ``retired`` record.
    """
    path = history_path(survey)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out = []
    for m in data.get(site) or []:
        if "retired" not in m:
            raise ValueError(f"{path.name}: {site} entry {m.get('start')} has no retired record")
        out.append({**normalise(m), "retired": _retired(m["retired"])})
    return out


def retire_masks(survey, site: str, select, why: str, on=None) -> list[dict]:
    """Move a site's masks that `select` picks from masks.yaml to masks_history.yaml.

    Each picked entry keeps its keys and gains ``retired: {on, why}``; the
    entries are appended to the end of the site's history block. The
    history is written first, then masks.yaml, both atomically
    (`replace_text`), so an interruption between the two leaves an entry
    in both files rather than in neither. A site block of masks.yaml left
    with no entry stays as ``<site>: []``.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.
        select (callable): Takes a normalised mask, returns True to retire it.
        why (str): Why the entries are taken out of use.
        on (date-like, optional): The date recorded; today (local) when None.

    Returns:
        list of dict: The retired entries as written to the history, with
        their ``retired`` record; empty when `select` picks none, in which
        case neither file is written.

    Raises:
        ValueError: If `why` is empty.
    """
    record = _retired({"on": on if on is not None else dt.date.today().isoformat(), "why": why})
    current = load_masks(survey, site)
    chosen = [bool(select(m)) for m in current]
    picked = [m for m, c in zip(current, chosen) if c]
    if not picked:
        return []
    kept = [m for m, c in zip(current, chosen) if not c]
    retired = [{**m, "retired": dict(record)} for m in picked]
    history = load_history(survey, site) + retired
    _write_block(history_path(survey), HISTORY_HEADER, site, [stored(m) for m in history], keep_empty=True)
    save_masks(survey, site, kept, keep_empty=True)
    logger.info(f"{site}: {len(picked)} mask(s) retired to {history_path(survey).name} ({record['why']})")
    return retired


def restore_masks(survey, site: str, select) -> list[dict]:
    """Move a site's history entries that `select` picks back into masks.yaml.

    The entries lose their ``retired`` record and join the site's masks,
    sorted and collapsed as `save_masks` does. masks.yaml is written first,
    then the history, both atomically; a history block left with no entry
    stays as ``<site>: []``.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.
        select (callable): Takes a history entry (normalised, with its
            ``retired`` record), returns True to restore it.

    Returns:
        list of dict: The restored entries, normalised, without ``retired``;
        empty when `select` picks none, in which case neither file is written.
    """
    history = load_history(survey, site)
    chosen = [bool(select(m)) for m in history]
    picked = [m for m, c in zip(history, chosen) if c]
    if not picked:
        return []
    left = [m for m, c in zip(history, chosen) if not c]
    restored = [normalise(m) for m in picked]
    save_masks(survey, site, load_masks(survey, site) + restored, keep_empty=True)
    _write_block(history_path(survey), HISTORY_HEADER, site, [stored(m) for m in left], keep_empty=True)
    logger.info(f"{site}: {len(restored)} mask(s) restored from {history_path(survey).name}")
    return restored


def union_masks(*mask_lists) -> list[dict]:
    """Join the masks of several sites into one list.

    The result is normalised and sorted earliest first. A mask with the same
    interval, bands and channels at two sites is kept once, as the first
    site's entry.

    Args:
        *mask_lists: Lists of masks; None is treated as empty.

    Returns:
        list of dict: The joined masks.
    """
    return _ordered(m for masks in mask_lists for m in masks or [])


STACK_PREFIX = "STK_"


def is_stack(site) -> bool:
    """Return True for the name of a stacked remote.

    Stacked remotes built by scripts/campaign.py are named
    ``STK_<site>u`` or ``STK_<site>w``. A stack combines several sites and
    has no masks.yaml entry of its own.
    """
    return str(site or "").startswith(STACK_PREFIX)


def masks_for_role(masks, role: str, rule: str = "role") -> list[dict]:
    """Return the masks of one site that apply when the site plays `role` in a pair.

    Under the rule ``role`` the masks of scope ``local`` and ``both`` apply
    to the local, and those of scope ``both`` and ``remote`` to the remote.
    Under the rule ``union`` every mask applies in both roles. The scope
    alone decides; a mask's ``channels`` are applied after it
    (`remote_channel_split` for the remote, `masks_for_row` for the local).

    Args:
        masks (iterable of dict): The site's masks; None is treated as empty.
        role (str): ``local`` or ``remote`` (`ROLES`).
        rule (str): ``role`` (the default) or ``union`` (`SCOPE_RULES`).

    Returns:
        list of dict: The masks that apply, normalised, in the order given.

    Raises:
        ValueError: If role is not one of `ROLES`, rule is not one of
            `SCOPE_RULES`, or a mask does not pass `normalise`.
    """
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, not {role!r}")
    if rule not in SCOPE_RULES:
        raise ValueError(f"mask scope rule must be one of {SCOPE_RULES}, not {rule!r}")
    masks = [normalise(m) for m in masks or []]
    if rule == "union":
        return masks
    return [m for m in masks if m["scope"] in SCOPES_OF_ROLE[role]]


def cuts_whole_window(mask: dict) -> bool:
    """Return True when a mask leaves out whole STFT windows: it names hx or hy, or every channel.

    Such a mask applies to every output row in the local role and applies
    in the remote role; one naming only output channels (ex, ey, hz) does
    neither.
    """
    channels = normalise(mask)["channels"]
    return channels == "all" or any(c in WHOLE_WINDOW for c in channels)


def masks_for_row(masks, row: str) -> list[dict]:
    """Return the masks that apply to one output row of a local site's transfer function.

    A row takes the masks that leave out whole windows (`cuts_whole_window`)
    and the masks naming it.

    Args:
        masks (iterable of dict): Masks applied in the local role; None is
            treated as empty.
        row (str): An output channel, one of `OUTPUTS`.

    Returns:
        list of dict: The masks that apply, normalised, in the order given.

    Raises:
        ValueError: If row is not one of `OUTPUTS`.
    """
    if row not in OUTPUTS:
        raise ValueError(f"row must be one of {OUTPUTS}, not {row!r}")
    out = []
    for m in (normalise(m) for m in masks or []):
        if cuts_whole_window(m) or row in m["channels"]:
            out.append(m)
    return out


def remote_channel_split(masks) -> tuple[list[dict], list[dict]]:
    """Split a remote's masks into those that apply and those its channels leave out.

    The remote contributes its hx and hy alone, so a mask naming neither
    (only ex, ey or hz) does not apply there; one naming hx, hy or every
    channel applies as a whole-window cut.

    Args:
        masks (iterable of dict): The remote's masks its scope lets apply.

    Returns:
        tuple: ``(applied, left_out)``, each normalised, in the order given.
    """
    masks = [normalise(m) for m in masks or []]
    return [m for m in masks if cuts_whole_window(m)], [m for m in masks if not cuts_whole_window(m)]


def remote_masks(survey, remote, rule: str = "role", channels: bool = True) -> list[dict]:
    """Return the masks a run takes from its remote.

    These are the remote's masks of scope ``both`` or ``remote``
    (`masks_for_role`), or all of its masks under the rule ``union``, that
    name hx, hy or every channel (`remote_channel_split`; `channels` False
    skips this step and returns every mask the scope lets apply). The choice
    depends on the remote's name alone (`is_stack`), so a site's masks apply
    whether or not its raw folder or archive is available.
    scripts/process_rr.py, the campaign signature and the GUI Process tab
    all use this function. A stack built under another name (a
    scripts/build_stack.py name without the prefix) is read like a site,
    and whatever masks.yaml holds under that name applies.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        remote (str): Remote site id, or empty for a single-site run.
        rule (str): ``role`` (the default) or ``union`` (`SCOPE_RULES`).
        channels (bool): Leave out the masks naming no magnetic input (the
            default).

    Returns:
        list of dict: The remote's masks that apply as the remote, or an
        empty list for no remote or a stack.

    Raises:
        ValueError: If rule is not one of `SCOPE_RULES`.
    """
    if rule not in SCOPE_RULES:
        raise ValueError(f"mask scope rule must be one of {SCOPE_RULES}, not {rule!r}")
    if not remote or is_stack(remote):
        return []
    masks = masks_for_role(load_masks(survey, remote), "remote", rule)
    return remote_channel_split(masks)[0] if channels else masks


def applies(mask: dict, period_s: float) -> bool:
    """Return True when a mask covers the band with centre period `period_s`.

    A mask covers a band when its ``bands`` is ``"all"`` or
    pmin_s <= period_s <= pmax_s. A mask picked on the polar panel of one
    band records that band's [pmin, pmax], so it covers that band and none
    of its neighbours, whose centres lie outside it.

    Args:
        mask (dict): A normalised mask.
        period_s (float): Centre period of the band in s.

    Returns:
        bool: Whether the mask applies to the band.
    """
    bands = mask["bands"]
    return bands == "all" or bands[0] <= float(period_s) <= bands[1]


def split_by_bands(masks) -> tuple[list[dict], list[dict]]:
    """Split masks into the ``bands: all`` ones and the band-limited ones.

    Returns:
        tuple: ``(all_band_masks, band_limited_masks)``, each normalised and
        in the order given.
    """
    masks = [normalise(m) for m in masks or []]
    return [m for m in masks if m["bands"] == "all"], [m for m in masks if m["bands"] != "all"]


def windows_in_mask(times, window_s: float, mask: dict) -> np.ndarray:
    """Flag the STFT windows that overlap a mask's [start, end).

    `times` is aurora's STFT ``time`` coordinate: naive datetime64 in UTC,
    holding the first sample of each window
    (`aurora.time_series.windowing_scheme.downsample_time_axis` keeps the
    left-hand window edges). Window k spans [times[k], times[k] + window_s),
    and is flagged when any of its samples lies inside the mask, matching
    the chunk rule of `crust.crosspower.masked_chunks`.

    Args:
        times (array-like): STFT window start times, datetime64.
        window_s (float): Window length in s, num_samples over the level's
            sample rate.
        mask (dict): A normalised mask.

    Returns:
        np.ndarray: Boolean array, one entry per window.

    Raises:
        TypeError: If `times` is not datetime64.
    """
    t = np.asarray(times)
    if t.dtype.kind != "M":
        raise TypeError(f"STFT window times must be datetime64, not {t.dtype}")
    t = t.astype("datetime64[ns]")
    start = np.datetime64(utc(mask["start"]).tz_convert(None).to_datetime64(), "ns")
    end = np.datetime64(utc(mask["end"]).tz_convert(None).to_datetime64(), "ns")
    length = np.timedelta64(int(round(float(window_s) * 1e9)), "ns")
    return (t < end) & (t + length > start)


def _merged(spans) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Merge overlapping or touching (start, end) spans, sorted by start."""
    out: list = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _cut(start, end, cuts) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """[start, end) with every (merged, sorted) interval in `cuts` taken out."""
    pieces, cursor = [], start
    for a, b in cuts:
        if b <= cursor or a >= end:
            continue
        if a > cursor:
            pieces.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < end:
        pieces.append((cursor, end))
    return pieces


def apply_time_masks(kd, masks, min_piece_s: float = MIN_PIECE_S):
    """Cut the ``bands: all`` masks out of a KernelDataset's run intervals.

    Every row of ``kd.df`` (the local station's runs and, in remote
    reference, the remote's) is split into the pieces of [start, end) left
    around the masks. A piece shorter than `min_piece_s` is dropped; a row
    no mask touches is kept as it is. Then, as in
    `crust.process.clip_to_window`, the duration column is refreshed and,
    when there is a remote, `restrict_run_intervals_to_simultaneous` pairs
    the local and remote pieces again. Band-limited masks are counted in the
    log line and left to the band patch in `crust.process` (see the module
    docstring).

    Args:
        kd (KernelDataset): Aurora kernel dataset, modified in place.
        masks (iterable of dict): Masks to apply.
        min_piece_s (float): Shortest piece kept, in s (default 600 s).

    Returns:
        KernelDataset: `kd`.

    Raises:
        ValueError: If the masks leave no data to process.
    """
    masks = [normalise(m) for m in masks or []]
    cuts = _merged((utc(m["start"]), utc(m["end"])) for m in masks if m["bands"] == "all")
    skipped = sum(m["bands"] != "all" for m in masks)
    if not cuts:
        if skipped:
            logger.info(f"{skipped} band-limited mask(s) left to the band patch (crust.process)")
        return kd
    keep, starts, ends, dropped = [], [], [], 0
    for index, row in kd.df.iterrows():
        start, end = utc(row["start"]), utc(row["end"])
        pieces = _cut(start, end, cuts)
        if pieces == [(start, end)]:
            keep.append(index), starts.append(start), ends.append(end)
            continue
        for a, b in pieces:
            if (b - a).total_seconds() < min_piece_s:
                dropped += 1
                continue
            keep.append(index), starts.append(a), ends.append(b)
    if not keep:
        raise ValueError("the time masks leave no data to process")
    df = kd.df.loc[keep].copy()
    df["start"], df["end"] = starts, ends
    kd.df = df.reset_index(drop=True)
    kd._update_duration_column()
    if kd.remote_station_id:
        kd.df = kd.restrict_run_intervals_to_simultaneous(kd.df)
    masked_h = sum((b - a).total_seconds() for a, b in cuts) / 3600.0
    logger.info(f"time masks: {len(cuts)} interval(s), {masked_h:.2f} h cut; {dropped} piece(s) under "
                f"{min_piece_s / 60:g} min dropped; {skipped} band-limited mask(s) left to the band patch "
                f"-> {len(kd.df)} run interval(s), {kd.df.duration.sum() / 3600:.1f} station-hours")
    return kd
