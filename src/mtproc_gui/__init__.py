# -*- coding: utf-8 -*-
"""
Desktop GUI for the MT processing workflow

A PySide6 and pyqtgraph front end over `scripts/` and the per-survey YAML. The
GUI selects a survey, shows its contents, draws the archives and runs the
command-line scripts as subprocesses. Product computations live in
`src/mtproc/` and are reached through the scripts in `scripts/`.

Run it with::

    python -m mtproc_gui [surveys/<name>/survey.yaml]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

__all__ = ["app", "jobs", "archive"]
