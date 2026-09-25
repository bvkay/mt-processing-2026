# -*- coding: utf-8 -*-
"""
The one place the MANTLE package is imported

MANTLE (Magnetotelluric ANalysis with Truth-Led Estimation) is installed
today under its provisional import name and is being renamed; `PACKAGE`
resolves whichever of the two names imports, and `module` and `version`
give the seam module its submodules and its version string. The rename
therefore touches `CANDIDATES` alone.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path
from types import ModuleType

CANDIDATES = ("mantle", "mt_proc")  # the planned import name first, the provisional one second


def _resolve() -> ModuleType:
    """Import the first candidate name that resolves."""
    errors = []
    for name in CANDIDATES:
        try:
            return importlib.import_module(name)
        except ImportError as exc:
            errors.append(f"{name}: {exc}")
    raise ImportError("the MANTLE package is not installed under any of " + ", ".join(CANDIDATES)
                      + " (" + "; ".join(errors) + ")")


PACKAGE = _resolve()
NAME = PACKAGE.__name__


def module(dotted: str) -> ModuleType:
    """Import a MANTLE submodule by its path below the package, for example ``io.mth5_reader``."""
    return importlib.import_module(f"{NAME}.{dotted}")


def repo_dir() -> Path:
    """The checkout the package is imported from (its parent folder)."""
    return Path(PACKAGE.__file__).resolve().parents[1]


def version() -> str:
    """Return the package version with the checkout's git state, for example ``0.0.1 git a1b2c3d uncommitted``."""
    base = str(getattr(PACKAGE, "__version__", "unknown"))
    try:
        def git(*args: str) -> str:
            return subprocess.run(["git", *args], cwd=repo_dir(), capture_output=True, text=True,
                                  check=True).stdout.strip()

        sha = git("rev-parse", "--short", "HEAD")
        dirty = " uncommitted" if git("status", "--porcelain") else ""
        return f"{base} git {sha}{dirty}"
    except Exception:
        return base
