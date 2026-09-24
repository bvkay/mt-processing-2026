"""Time masks: `<survey>/masks.yaml`, the intervals a student declares processing should leave out.

A declaration, like `filters.yaml`: the Cross-powers tab writes it when the
student presses "Save masks" and nothing else ever does. Per site, a list:

    C23:
    - start: '2023-09-22T12:05:49Z'   # UTC, ISO
      end: '2023-09-22T12:25:49Z'
      bands: all                      # or [pmin_s, pmax_s]
      reason: mains switching         # free text
      found_by: time                  # time | polar: the panel it was picked on

`load_masks(survey, site)` and `save_masks(survey, site, masks)` read and
write one site's block; saving rewrites **only that site's block** of the
file's text, so every other site's block (and the leading comment) stays
byte-identical. `apply_time_masks(kd, masks)` cuts the masked intervals out
of an aurora KernelDataset; `applies(mask, period_s)` is the one rule for
which bands a mask covers (the tab's hollow spots, `mtproc.crosspower.
masked_chunks` and `stack_impedance` all ask it).

**What reaches processing.** scripts/process_rr.py loads the site's masks
and hands them to `mtproc.process.process_station(time_masks=...)`, which
calls `apply_time_masks` on the kernel dataset with the masks whose `bands`
is `all`: each run interval is split around them, so aurora never sees
those samples. A band-limited mask (`bands: [pmin_s, pmax_s]`, what a
selection on the Cross-powers tab's polar panel records) reaches aurora
through a scoped runtime patch instead:
`mtproc.process._band_masks_applied` drops the STFT windows it overlaps
(`windows_in_mask`) from each band whose centre period it covers
(`applies`), before the regression. Aurora 0.6.2 has no input for that
(checked in its source; docs/upstream_issues.md 22, and the
prepared fix in docs/upstream_patches/):

- `DecimationLevel.channel_weight_specs[].weights` is the only weight a
  config carries, and `aurora.pipelines.feature_weights.calculate_weights`
  overwrites it (``chws.weights = weights``, None when the spec has no
  feature weight specs) just before the regression;
- the regression then uses it as ``band_weights = weights.mean(axis=1)``
  (`aurora.pipelines.transfer_function_helpers.
  process_transfer_functions_with_weights`) -- one weight per STFT window,
  the same for every band of the level; the per-band lookup
  (``chws.get_weights_for_band(band)``) is commented out there;
- `process_mth5_legacy` builds the merged STFT objects and passes them
  straight to the regression, with no callback between, and mth5's
  `apply_masks_and_weights` ("add this method to tf-estimation right before
  robust regression") is an empty stub.

A band mask is also used by `mtproc.crosspower.stack_impedance`, the
classical stacked remote-reference estimate from the kept chunks'
cross-powers.
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
    "# Time masks declared on the GUI's Cross-powers tab (mtproc.masks): per site, the\n"
    "# intervals processing leaves out. bands: all (cut in time), or [pmin_s, pmax_s] (left\n"
    "# out of the bands whose centre period lies inside; see mtproc.masks). Times are UTC.\n"
)


class _Dumper(yaml.SafeDumper):
    """Block style, except a list of plain numbers (a mask's bands) on one line: [0.02, 0.1]."""


_Dumper.add_representer(
    list, lambda dumper, data: dumper.represent_sequence(
        "tag:yaml.org,2002:seq", data,
        flow_style=all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in data) and bool(data)))


def masks_path(survey) -> Path:
    """`<survey folder>/masks.yaml` for a `Survey`, a survey.yaml path or the survey folder."""
    folder = getattr(survey, "config_dir", None)
    if folder is None:
        folder = Path(survey)
        if folder.suffix.lower() in (".yaml", ".yml"):
            folder = folder.parent
    return Path(folder) / MASKS_FILE


def utc(value) -> pd.Timestamp:
    """A UTC-aware Timestamp (naive text is UTC)."""
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def iso(value) -> str:
    """'2023-09-22T12:05:49Z' (fractions of a second kept when there are any)."""
    return utc(value).isoformat().replace("+00:00", "Z")


def normalise(mask: dict) -> dict:
    """One mask with its keys in the file's order and its values checked; ValueError if not a mask."""
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
    """Normalised, earliest first, the same interval and bands declared twice (a repeated
    click on the Cross-powers tab) kept once."""
    out, seen = [], set()
    for m in sorted((normalise(m) for m in masks), key=lambda m: m["start"]):
        key = (m["start"], m["end"], str(m["bands"]))
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def load_masks(survey, site: str) -> list[dict]:
    """`site`'s masks from masks.yaml, normalised, earliest first, duplicates collapsed
    ([] with no file or no entry)."""
    path = masks_path(survey)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _ordered(data.get(site) or [])


def _blocks(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(the text before the first site, [(site, its block's text)]): a block runs from its
    unindented key line to the next one, the comments and blank lines after it included."""
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
    """Write `site`'s masks (normalised, earliest first, duplicates collapsed); an empty
    list removes its block.

    Only that site's block of the file changes: the other sites' blocks and
    the leading comment are carried over as text, byte for byte.
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


def applies(mask: dict, period_s: float) -> bool:
    """True when `mask` (normalised) covers the band whose centre period is `period_s`:
    `bands: all`, or pmin_s <= period_s <= pmax_s. A mask picked on one band's polar
    panel records that band's own [pmin, pmax], so it covers that band and no neighbour
    (a neighbour's centre lies outside it)."""
    bands = mask["bands"]
    return bands == "all" or bands[0] <= float(period_s) <= bands[1]


def split_by_bands(masks) -> tuple[list[dict], list[dict]]:
    """(the `bands: all` masks, the band-limited ones), each normalised, in the order given."""
    masks = [normalise(m) for m in masks or []]
    return [m for m in masks if m["bands"] == "all"], [m for m in masks if m["bands"] != "all"]


def windows_in_mask(times, window_s: float, mask: dict) -> np.ndarray:
    """Per STFT window, True when the window overlaps `mask`'s [start, end).

    `times` is aurora's STFT `time` coordinate: naive datetime64 in UTC, each
    window's FIRST sample (`aurora.time_series.windowing_scheme.
    downsample_time_axis` keeps the left-hand window edges). A window lasts
    `window_s` (num_samples over the level's sample rate), so window k spans
    [times[k], times[k] + window_s); one with any sample inside the mask is
    hit, as a chunk a mask overlaps is (`mtproc.crosspower.masked_chunks`).
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
    """Cut the `bands: all` masks out of the KernelDataset's run intervals (in place; returns `kd`).

    Every row of `kd.df` (the local station's runs and, in RR, the remote's)
    is split into the pieces [start, end) leaves around the masks; a piece a
    mask made shorter than `min_piece_s` (10 min) is dropped, a row no mask
    touches is kept as it is. Then, as `mtproc.process.clip_to_window` does,
    the duration column is refreshed and, when there is a remote,
    `restrict_run_intervals_to_simultaneous` pairs the local and remote
    pieces again. Band-limited masks are **not** applied (see the module
    docstring); they are counted in the log line. Raises ValueError when
    nothing is left.
    """
    masks = [normalise(m) for m in masks or []]
    cuts = _merged((utc(m["start"]), utc(m["end"])) for m in masks if m["bands"] == "all")
    skipped = sum(m["bands"] != "all" for m in masks)
    if not cuts:
        if skipped:
            logger.info(f"{skipped} band-limited mask(s) left to the band patch (mtproc.process)")
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
