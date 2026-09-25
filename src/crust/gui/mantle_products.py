# -*- coding: utf-8 -*-
"""
The engine and the MANTLE report behind a processed EDI

A product of `scripts/process_rr.py` is an EDI with a `.json` sidecar of the
same stem. `engine_of` reads the sidecar's `engine` (a sidecar without the
key is an aurora run; an EDI without a sidecar is older than the naming
rule). A MANTLE run writes two more files the sidecar names,
`mantle_report` (MANTLE's report JSON: per-frequency verdicts, error and
degrees-of-freedom summaries, plain-language notes) and `mantle_fine_edi`
(its fine-grid EDI, `<stem>_fine.edi`, which `describe` labels as such).

`report_of` returns the report of a MANTLE product and `word_ranges`
regroups its verdicts for drawing: every verdict names a word and the
frequencies it judged, and the strip on the View EDIs tab shows, per word,
the period ranges those frequencies cover. `word_counts` reads the sidecar's
verdict tally and `notes_text` lays the report's summary and notes out as
plain text. The files are read only; nothing is computed from the data.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from crust.gui.theme import BAD_COLOUR, IDLE_COLOUR, OK_COLOUR, PAIR_REMOTE_COLOUR, WARN_COLOUR

FINE_SUFFIX = "_fine"
GAP_RATIO = 1.5  # neighbouring periods further apart than this start a new range
# one colour per MANTLE archive word, in the order the strip lists them
WORD_COLOURS = {
    "ok": OK_COLOUR,
    "snr_limited": WARN_COLOUR,
    "low_dof": PAIR_REMOTE_COLOUR,
    "ill_conditioned": BAD_COLOUR,
    "singular": "#b71c1c",
    "rr_incoherent": "#ff7043",
    "undefined_insufficient_dof": "#ba68c8",
}


def product_stem(edi_path: Path | str) -> str:
    """Return the product stem of an EDI: its stem, with a MANTLE fine-grid EDI's suffix removed."""
    stem = Path(edi_path).stem
    return stem[: -len(FINE_SUFFIX)] if stem.endswith(FINE_SUFFIX) else stem


def sidecar_path(edi_path: Path | str) -> Path:
    """Return the `.json` sidecar beside an EDI (the product stem's, for a fine-grid EDI)."""
    edi_path = Path(edi_path)
    return edi_path.with_name(product_stem(edi_path) + ".json")


@lru_cache(maxsize=256)
def _read_json(path: str, mtime_ns: int) -> dict:
    """Read a JSON file, cached on path and modification time."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read_json(path: Path | str) -> dict | None:
    """Return a JSON file's contents, or None when it is missing or unreadable."""
    path = Path(path)
    try:
        return _read_json(str(path), path.stat().st_mtime_ns)
    except (OSError, ValueError):
        return None


def sidecar_of(edi_path: Path | str) -> dict | None:
    """Return the sidecar of a product, or None without one."""
    return read_json(sidecar_path(edi_path))


def engine_of(edi_path: Path | str) -> str | None:
    """Return the engine that made an EDI: the sidecar's `engine`, "aurora" without the key, None without a sidecar."""
    sidecar = sidecar_of(edi_path)
    if sidecar is None:
        return None
    return str(sidecar.get("engine") or "aurora")


def describe(edi_path: Path | str) -> str:
    """Return the label suffix of an EDI row: "[<engine>]", "[mantle fine grid]" for a fine-grid EDI, "" without a sidecar."""
    engine = engine_of(edi_path)
    if engine is None:
        return ""
    fine = Path(edi_path).stem.endswith(FINE_SUFFIX) and engine != "aurora"
    return f"[{engine} fine grid]" if fine else f"[{engine}]"


def report_of(edi_path: Path | str) -> dict | None:
    """Return the MANTLE report of a product, or None for another engine or a missing file."""
    sidecar = sidecar_of(edi_path)
    if not sidecar or not sidecar.get("mantle_report"):
        return None
    return read_json(Path(edi_path).with_name(str(sidecar["mantle_report"])))


def word_counts(sidecar: dict | None) -> dict[str, int]:
    """Return the sidecar's verdict tally (`engine_config.verdict_words`), {} without one."""
    if not sidecar:
        return {}
    words = (sidecar.get("engine_config") or {}).get("verdict_words") or {}
    return {str(k): int(v) for k, v in words.items()}


def _ranges(periods: np.ndarray) -> list[tuple[float, float]]:
    """Group sorted periods into (shortest, longest) ranges, split where neighbours are over GAP_RATIO apart."""
    out: list[tuple[float, float]] = []
    if periods.size == 0:
        return out
    start = periods[0]
    for a, b in zip(periods[:-1], periods[1:], strict=True):
        if b / a > GAP_RATIO:
            out.append((float(start), float(a)))
            start = b
    out.append((float(start), float(periods[-1])))
    return out


def word_ranges(report: dict | None) -> dict[str, list[tuple[float, float]]]:
    """Return, per verdict word, the period ranges (s) its verdicts cover.

    The verdicts of one word are pooled over gates and components, so a
    word's row on the strip shows every period some referee judged with it.

    Args:
        report (dict | None): A MANTLE report.

    Returns:
        dict: Word to a list of ``(pmin, pmax)`` in seconds, in the order of
        `WORD_COLOURS` and then any other word; {} without verdicts.
    """
    if not report:
        return {}
    freqs: dict[str, list[float]] = {}
    for verdict in report.get("verdicts") or []:
        word = str(verdict.get("word") or "")
        scope = verdict.get("freq_hz") or []
        if word and scope:
            freqs.setdefault(word, []).extend(float(f) for f in scope if f and f > 0)
    ordered = [w for w in WORD_COLOURS if w in freqs] + sorted(w for w in freqs if w not in WORD_COLOURS)
    return {w: _ranges(np.sort(1.0 / np.unique(np.asarray(freqs[w], dtype=float)))) for w in ordered}


def colour_of(word: str) -> str:
    """Return the strip colour of a word; grey for a word outside `WORD_COLOURS`."""
    return WORD_COLOURS.get(word, IDLE_COLOUR)


def notes_text(report: dict | None, title: str = "") -> str:
    """Lay out a MANTLE report's summary lines and notes as plain text."""
    if not report:
        return "no MANTLE report"
    lines = [title] if title else []
    period = report.get("period_s") or [None, None]
    lines.append(f"site {report.get('site_id', '?')}: {report.get('n_freq', '?')} frequencies, "
                 f"{period[0]:.4g} to {period[1]:.4g} s" if None not in period else
                 f"site {report.get('site_id', '?')}: {report.get('n_freq', '?')} frequencies")
    status = report.get("status") or {}
    if status:
        lines.append("solve status: " + ", ".join(f"{k} {v}" for k, v in status.items()))
    dof = report.get("dof") or {}
    if dof:
        lines.append("degrees of freedom: " + ", ".join(f"{k} {v:g}" for k, v in dof.items()))
    error = report.get("error") or {}
    if error:
        lines.append("median error: " + ", ".join(f"{k} {v:.3g}" for k, v in error.items()))
    lines.append(f"snr gate ran: {report.get('snr_gate_ran')}")
    lines.append("")
    lines.append("notes:")
    for note in report.get("notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines)
