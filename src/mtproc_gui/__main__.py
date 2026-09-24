# -*- coding: utf-8 -*-
"""
Entry point for ``python -m mtproc_gui [survey.yaml]``

The optional argument is a survey config, for example
``surveys/curnamona_cube/survey.yaml``. Without it the window opens empty and
the survey is chosen from the File menu or the Metadata tab. The theme in
`mtproc_gui.theme` (dark grey surface, channel colours) is applied to the
application before the window is built.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from mtproc_gui import theme
from mtproc_gui.app import MainWindow


def main(argv: list[str] | None = None) -> int:
    """Build the main window and run the Qt event loop.

    Args:
        argv (list[str] | None): Command-line arguments; ``argv[1]``, when
            present, is the survey YAML to open. Defaults to ``sys.argv``.

    Returns:
        int: The exit code of the Qt application.
    """
    argv = list(sys.argv if argv is None else argv)
    survey_yaml = argv[1] if len(argv) > 1 else None

    app = QApplication(argv)
    theme.apply(app)
    window = MainWindow(survey_yaml=survey_yaml)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
