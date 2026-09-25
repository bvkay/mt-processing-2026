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
      found_by: time                  # time | polar: the panel it was picked on

`load_masks(survey, site)` and `save_masks(survey, site, masks)` read and
write one site's block. Saving rewrites that site's block of the file's text
and carries the other blocks and the leading comment over unchanged.
`apply_time_masks(kd, masks)` cuts the masked intervals out of an aurora
KernelDataset. `applies(mask, period_s)` decides which bands a mask covers;
the Cross-powers tab, `crust.crosspower.masked_chunks` and
`crust.crosspower.stack_impedance` all use it.

Masks in processing: scripts/process_rr.py loads the masks of the local site
and of the remote site (`remote_masks`; a stacked remote named `STK_...` has
none), joins them with `union_masks`, and passes the union to
`crust.process.process_station(time_masks=...)`. A remote-referenced
estimate uses the samples of both stations, so noise at either one is left
out. `process_station` calls `apply_time_masks` with the masks whose `bands`
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
estimate from the cross-powers of the kept chunks, also applies band masks.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from loguru import logger

MASKS_FILE = "masks.yaml"
MIN_PIECE_S = 600.0  # a run piece a mask leaves shorter than this is dropped
FOUND_BY = ("time", "polar")
HEADER = (
    "# Time masks declared on the GUI's Cross-powers tab (crust.masks): per site, the\n"
    "# intervals processing leaves out. bands: all (cut in time), or [pmin_s, pmax_s] (left\n"
    "# out of the bands whose centre period lies inside; see crust.masks). Times are UTC.\n"
)


class _Dumper(yaml.SafeDumper):
    """YAML dumper in block style that writes a list of plain numbers on one line.

    A mask's bands are written as ``[0.02, 0.1]``.
    """


_Dumper.add_representer(
    list, lambda dumper, data: dumper.represent_sequence(
        "tag:yaml.org,2002:seq", data,
        flow_style=all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data) and bool(data)))


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


def normalise(mask: dict) -> dict:
    """Check one mask and return it with its keys in the file's order.

    Args:
        mask (dict): Mask with ``start`` and ``end`` and optional ``bands``,
            ``reason`` and ``found_by``.

    Returns:
        dict: ``{"start", "end", "bands", "reason", "found_by"}``, times as
        ISO UTC text, ``bands`` as ``"all"`` or a sorted ``[pmin_s, pmax_s]``.

    Raises:
        ValueError: If start or end is missing or unparseable, end is not
            after start, bands is malformed, or found_by is not one of
            `FOUND_BY`.
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
    return {"start": iso(start), "end": iso(end), "bands": bands,
            "reason": str(mask.get("reason") or ""), "found_by": found_by}


def _ordered(masks) -> list[dict]:
    """Normalise masks, sort them earliest first and collapse duplicates.

    A mask with the same interval and bands as an earlier one, for example
    from a repeated click on the Cross-powers tab, is kept once.
    """
    out, seen = [], set()
    for m in sorted((normalise(m) for m in masks), key=lambda m: m["start"]):
        key = (m["start"], m["end"], str(m["bands"]))
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


def save_masks(survey, site: str, masks) -> Path:
    """Write the masks of one site to masks.yaml.

    The masks are normalised, sorted earliest first and collapsed as in
    `load_masks`. The site's block is replaced; the other sites' blocks and
    the leading comment are carried over as text, unchanged. A new file
    starts with `HEADER`.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        site (str): Site id.
        masks (iterable of dict): The site's masks. An empty list removes
            the site's block.

    Returns:
        Path: The masks.yaml path.
    """
    path = masks_path(survey)
    entries = _ordered(masks)
    text = path.read_text(encoding="utf-8") if path.exists() else HEADER
    header, blocks = _blocks(text)
    new = (yaml.dump({site: entries}, Dumper=_Dumper, sort_keys=False, allow_unicode=True,
                     default_flow_style=False, width=100) if entries else "")
    out, placed = [], False
    for key, chunk in blocks:
        if key == site:
            out.append(new)
            placed = True
        else:
            out.append(chunk if chunk.endswith("\n") else chunk + "\n")
    if not placed and new:
        out.append(new)
    if header and not header.endswith("\n"):
        header += "\n"
    path.write_text(header + "".join(out), encoding="utf-8")
    logger.info(f"{site}: {len(entries)} mask(s) written to {path}")
    return path


def union_masks(*mask_lists) -> list[dict]:
    """Join the masks of several sites into one list.

    The result is normalised and sorted earliest first. A mask with the same
    interval and bands at two sites is kept once, as the first site's entry.

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


def remote_masks(survey, remote) -> list[dict]:
    """Return the masks a run takes from its remote.

    The choice depends on the remote's name alone (`is_stack`), so a site's
    masks apply whether or not its raw folder or archive is available.
    scripts/process_rr.py, the campaign signature and the GUI Process tab
    all use this function. A stack built under another name (a
    scripts/build_stack.py name without the prefix) is read like a site, and
    whatever masks.yaml holds under that name applies.

    Args:
        survey (Survey or str or Path): Survey, survey.yaml path or folder.
        remote (str): Remote site id, or empty for a single-site run.

    Returns:
        list of dict: ``load_masks(survey, remote)``, or an empty list for
        no remote or a stack.
    """
    return [] if not remote or is_stack(remote) else load_masks(survey, remote)


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
