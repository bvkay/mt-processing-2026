# -*- coding: utf-8 -*-
"""
The index of a workspace's processed products, `<workspace>/tf/index.json`

Every product of `scripts/process_rr.py` is an EDI with a `.json` sidecar of
the same stem, and the View EDIs tab labels each row by the sidecar's
`engine`. A sidecar is about 134 kB (the Atlas workspace holds 4,398 of
them, 588 MB), so reading every one to label the list took 5-6 s per
reload. The index keeps, per product stem, the facts the list needs and
the sidecar's modification time and size they were read at::

    {"products": {"C18_rr-C19_20260924-1530": {"engine": "aurora", "fine": false,
                                               "mtime_ns": 1758695400000000000, "size": 133842}}}

`fine` is whether the sidecar names a MANTLE fine-grid EDI. `add` records
one product (`mt_workbench.products.write_products` calls it as a product
lands); `facts` returns the facts of many stems, from what this process
already holds, then the index file, and reads only the sidecars that
neither covers or whose time or size moved, saving the index again when it
read any. Entries are kept in-process without bound (a few hundred bytes
each). The file is written atomically (`mt_workbench.masks.replace_text`);
two runs landing at once may each drop the other's entry, which the next
`facts` call reads back from the sidecar. Reading a product needs only its
sidecar, which stays the record.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from loguru import logger

from mt_workbench.masks import replace_text

INDEX_FILE = "index.json"
# sidecar path -> ((st_mtime_ns, st_size), facts): every sidecar read or indexed in this process
_KEPT: dict[str, tuple[tuple[int, int], dict]] = {}
_LOADED: set[str] = set()  # tf folders whose index file this process has read


def index_path(tf_dir) -> Path:
    """Return `<tf_dir>/index.json`."""
    return Path(tf_dir) / INDEX_FILE


def sidecar_facts(sidecar: dict) -> dict:
    """Return the facts the index keeps from a sidecar: its engine ("aurora" without the key) and fine-grid flag."""
    return {"engine": str(sidecar.get("engine") or "aurora"), "fine": bool(sidecar.get("mantle_fine_edi"))}


def _read_sidecar(path: Path) -> dict | None:
    """Return a sidecar's facts, or None when it is missing or not JSON."""
    try:
        with open(path, encoding="utf-8") as handle:
            return sidecar_facts(json.load(handle))
    except (OSError, ValueError, AttributeError):
        return None


def _load(tf_dir: Path) -> dict:
    """Return the index file's products, {} when it is missing or unreadable."""
    try:
        with open(index_path(tf_dir), encoding="utf-8") as handle:
            products = json.load(handle).get("products") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return products if isinstance(products, dict) else {}


def _save(tf_dir: Path, products: dict) -> None:
    """Write the index file atomically; a folder that cannot be written is left as it was, with a log line."""
    text = json.dumps({"products": dict(sorted(products.items()))}, indent=1) + "\n"
    try:
        replace_text(index_path(tf_dir), text)
    except OSError as exc:
        logger.warning(f"{index_path(tf_dir)} not written: {exc}")


def _entry(stamp: tuple[int, int], facts: dict) -> dict:
    """Return an index entry: the facts with the sidecar's mtime and size."""
    return {**facts, "mtime_ns": stamp[0], "size": stamp[1]}


def add(edi_path) -> None:
    """Record the product of an EDI in its folder's index, from the sidecar beside it.

    Does nothing without a readable sidecar. Never raises: the index only
    speeds up the View EDIs list.

    Args:
        edi_path (str or Path): The product's EDI, ``<tf_dir>/<stem>.edi``.
    """
    edi_path = Path(edi_path)
    sidecar = edi_path.with_suffix(".json")
    try:
        status = sidecar.stat()
    except OSError:
        return
    facts = _read_sidecar(sidecar)
    if facts is None:
        return
    stamp = (status.st_mtime_ns, status.st_size)
    _KEPT[os.path.abspath(sidecar)] = (stamp, facts)
    products = _load(edi_path.parent)
    products[edi_path.stem] = _entry(stamp, facts)
    _save(edi_path.parent, products)


def facts(tf_dir, stems, files: dict[str, tuple[int, int]] | None = None) -> dict[str, dict | None]:
    """Return the facts of each product stem's sidecar, reading only sidecars not indexed as they are.

    Args:
        tf_dir (str or Path): The products folder.
        stems (iterable of str): Product stems (`mt_workbench.gui.mantle_products.product_stem`).
        files (dict | None): ``{file name: (st_mtime_ns, st_size)}`` of the
            folder, from one listing (`listing`); taken here when None.

    Returns:
        dict: Stem to ``{"engine", "fine"}``, or None for a stem with no
        readable sidecar.
    """
    tf_dir = Path(tf_dir)
    files = listing(tf_dir) if files is None else files
    key_dir = os.path.abspath(tf_dir)
    if key_dir not in _LOADED:  # the file seeds this process's entries once
        _LOADED.add(key_dir)
        for stem, entry in _load(tf_dir).items():
            try:
                stamp = (int(entry["mtime_ns"]), int(entry["size"]))
                kept = {"engine": str(entry["engine"]), "fine": bool(entry.get("fine"))}
            except (KeyError, TypeError, ValueError):
                continue
            _KEPT.setdefault(os.path.join(key_dir, f"{stem}.json"), (stamp, kept))
    out, read = {}, {}
    for stem in stems:
        stamp = files.get(f"{stem}.json")
        if stamp is None:
            out[stem] = None
            continue
        path = os.path.join(key_dir, f"{stem}.json")
        kept = _KEPT.get(path)
        if kept is not None and kept[0] == stamp:
            out[stem] = kept[1]
            continue
        found = _read_sidecar(Path(path))
        out[stem] = found
        if found is not None:
            _KEPT[path] = (stamp, found)
            read[stem] = _entry(stamp, found)
    if read:
        products = _load(tf_dir)
        products.update(read)
        _save(tf_dir, products)
    return out


def listing(tf_dir) -> dict[str, tuple[int, int]]:
    """Return ``{file name: (st_mtime_ns, st_size)}`` of a folder's files from one `os.scandir`.

    On Windows the directory listing carries each file's time and size, so
    this costs no call per file. {} for a missing folder.
    """
    try:
        with os.scandir(tf_dir) as entries:
            return {e.name: (e.stat().st_mtime_ns, e.stat().st_size) for e in entries if e.is_file()}
    except OSError:
        return {}
