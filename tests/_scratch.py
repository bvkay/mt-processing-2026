# -*- coding: utf-8 -*-
"""
Scratch and fork-clone locations for the tests

Portable scratch directories and fork-clone locations shared by tests/*.py.
The tests import it flat (`from _scratch import scratch_dir, fork_clone`), in
the same way as `import instrument_samples`. The test scripts run directly
(`python tests/whatever_unit.py`), so `tests/` is on `sys.path` without extra
setup.

Environment variables:
    CRUST_TEST_SCRATCH: base of the scratch directories (default: the OS
        temp directory).
    CRUST_FORKS: parent of the forked-dependency clones (default:
        DEFAULT_FORKS).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# The parent of the sibling git clones (mth5, mt-metadata, aurora, mt-io,
# mt-timeseries) the *_fork_unit.py tests look for, when CRUST_FORKS is unset.
DEFAULT_FORKS = Path("D:/BEN")


def scratch_dir(name: str) -> Path:
    """Return a scratch directory for one test, creating it if needed.

    Args:
        name (str): Name of the test's directory.

    Returns:
        Path: <CRUST_TEST_SCRATCH or the OS temp directory>/crust_tests/<name>.
    """
    base = Path(os.environ.get("CRUST_TEST_SCRATCH", tempfile.gettempdir()))
    path = base / "crust_tests" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def forks_dir(name: str) -> Path:
    """Return the expected clone location of a forked dependency.

    The path is returned whether or not the clone exists. The fork tests use it
    to name the expected location in a SKIPPED message and check for the clone
    with `fork_clone`.

    Args:
        name (str): Directory name of the fork, e.g. "mth5".

    Returns:
        Path: <CRUST_FORKS or DEFAULT_FORKS>/<name>.
    """
    base = Path(os.environ.get("CRUST_FORKS", str(DEFAULT_FORKS)))
    return base / name


def fork_clone(name: str) -> Path | None:
    """Return the clone directory of a forked dependency, if present.

    Args:
        name (str): Directory name of the fork, e.g. "mth5".

    Returns:
        Path | None: The `forks_dir` location when it holds a `.git` entry,
        otherwise None.
    """
    path = forks_dir(name)
    return path if (path / ".git").exists() else None
