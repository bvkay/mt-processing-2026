"""Entry point: ``python -m bbmt_gui [survey.yaml]``.

The optional argument is a survey config (e.g.
``surveys/curnamona_cube/survey.yaml``); without it the window opens empty and
the survey is chosen from the File menu or the Metadata tab. The look --
the dark grey surface and the channel colours -- is `bbmt_gui.theme`, applied
to the application before the window is built.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from bbmt_gui import theme
from bbmt_gui.app import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    survey_yaml = argv[1] if len(argv) > 1 else None

    app = QApplication(argv)
    theme.apply(app)
    window = MainWindow(survey_yaml=survey_yaml)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
