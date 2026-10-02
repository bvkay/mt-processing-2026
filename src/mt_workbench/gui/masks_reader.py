# -*- coding: utf-8 -*-
"""
masks.yaml parsed off the GUI thread

`mt_workbench.masks.load_masks` reads a site's masks from the parsed whole of
the survey's masks.yaml, which is parsed once per change of the file
(`mt_workbench.masks.read_document`); the Atlas survey's 8.1 MB file takes
about 3 s with libyaml. `MasksReader` sits on `State` and runs that parse in a
`ReadThread`, so the window stays live while it runs. A tab calls `request()`:
it returns True when a load would answer at once (no file, or the file parsed
as it is now) and otherwise starts the parse, one at a time, and returns
False; `ready` is emitted on the GUI thread once the parse has ended. A parse
error is kept by `read_document` and raised again by the next load, which the
tab reports as before. The Process tab's masks switch and the Cross-powers
tab's mask list ask on a survey open, a station change and the tab shown.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from mt_workbench.masks import is_current, masks_path, read_document
from mt_workbench.gui.reader import ReadThread


class MasksReader(QObject):
    """Parses the open survey's masks.yaml in a worker thread when it changed.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QObject | None): Qt parent.
    """

    ready = Signal()  # a parse ended: a load now answers from the parsed file (or raises its error)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.parses = 0  # parses started
        self._thread: ReadThread | None = None

    def path(self) -> Path | None:
        """Return the open survey's masks.yaml path, or None with no survey open."""
        return None if self.state.survey_yaml is None else masks_path(self.state.survey_yaml)

    def request(self) -> bool:
        """Return True when a load answers at once; otherwise start the parse and return False.

        Returns:
            bool: True with no survey, no masks.yaml, or the file parsed as
            it is now; False while a parse runs, `ready` following.
        """
        path = self.path()
        if path is None or is_current(path):
            return True
        if self._thread is None:
            thread = ReadThread(read_document, str(path), path, parent=self)
            thread.finished.connect(self._done)
            thread.finished.connect(thread.deleteLater)
            self._thread = thread
            self.parses += 1
            thread.start()
        return False

    def _done(self) -> None:
        """Forget the finished thread and tell the tabs."""
        self._thread = None
        self.ready.emit()

    def wait(self) -> None:
        """Block until a parse in flight ends; used on window close."""
        if self._thread is not None:
            self._thread.wait()
