# -*- coding: utf-8 -*-
"""
Entry point for ``python -m mt_workbench [survey.yaml]``

``python -m mt_workbench``, ``python -m mt_workbench.gui`` and the ``mt-workbench`` console
script all run `main`. The optional argument is a survey config, for example
``surveys/curnamona_cube/survey.yaml``. Without it the window opens empty and
the survey is chosen from the File menu or the Metadata tab. The theme in
`mt_workbench.gui.theme` (dark grey surface, channel colours) is applied to the
application before the window is built.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mt_workbench.gui import theme
from mt_workbench.gui.app import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Build the main window and run the Qt event loop.

    Args:
        argv (list[str] | None): Command-line arguments; the one optional
            positional argument is the survey YAML to open. Defaults to
            ``sys.argv``.

    Returns:
        int: The exit code of the Qt application, or 2 for a bad argument.
    """
    argv = list(sys.argv if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m mt_workbench",
        description="Open the mt-workbench GUI, on a survey when one is given.",
    )
    parser.add_argument("survey_yaml", nargs="?", default=None,
                        help="a survey's survey.yaml (default: open with no survey)")
    args = parser.parse_args(argv[1:])
    survey_yaml = args.survey_yaml
    if survey_yaml is not None and not Path(survey_yaml).is_file():
        parser.error(f"survey file not found: {survey_yaml}")

    app = QApplication(argv[:1])
    theme.apply(app)
    window = MainWindow(survey_yaml=survey_yaml)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
