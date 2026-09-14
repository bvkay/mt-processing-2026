"""Portable scratch and fork-clone locations shared by tests/*.py.

Imported flat (`from _scratch import scratch_dir, fork_clone`), the same way
`tests/*.py` already does `import instrument_samples`: these scripts run
directly (`python tests/whatever_unit.py`), so `tests/` -- this module's own
directory -- is on `sys.path` without any extra setup.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# The parent of the sibling git clones (mth5, mt-metadata, aurora, mt-io,
# mt-timeseries) the *_fork_unit.py tests look for, when MTPROC_FORKS is unset.
DEFAULT_FORKS = Path("D:/BEN")


def scratch_dir(name: str) -> Path:
    """A scratch directory for one test, created on demand.

    Under MTPROC_TEST_SCRATCH (default: the OS temp directory) / mtproc_tests / <name>.
    """
    base = Path(os.environ.get("MTPROC_TEST_SCRATCH", tempfile.gettempdir()))
    path = base / "mtproc_tests" / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def forks_dir(name: str) -> Path:
    """Where the clone of a forked dependency named `name` would be, whether or not it's there.

    Under MTPROC_FORKS (default: DEFAULT_FORKS, i.e. D:\\BEN) / <name>. Fork tests
    use this only to name the expected location in a SKIPPED message; `fork_clone`
    is what they check.
    """
    base = Path(os.environ.get("MTPROC_FORKS", str(DEFAULT_FORKS)))
    return base / name


def fork_clone(name: str) -> Path | None:
    """The clone directory for a forked dependency, or None if there isn't one.

    See `forks_dir` for the location; a clone is one holding a `.git` entry.
    """
    path = forks_dir(name)
    return path if (path / ".git").exists() else None
