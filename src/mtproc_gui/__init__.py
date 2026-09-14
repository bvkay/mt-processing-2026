"""Desktop GUI for the MT processing workflow (PySide6 + pyqtgraph).

A launcher and viewer over `scripts/` and the per-survey YAML: the GUI picks a
survey, shows what is in it, draws the archives, and runs the existing
command-line scripts as subprocesses. No processing code lives here -- if a
number has to be computed from the data to make a product, it belongs in
`src/mtproc/` and is reached through a script in `scripts/`.

Run it with::

    python -m mtproc_gui [surveys/<name>/survey.yaml]
"""

__all__ = ["app", "jobs", "archive"]
