"""Spectra tab: the loaded window's PSDs as the MATLAB app's Welch tab laid them out.

The live view of the window picked on the Time Series tab: when the store's
`qc_ready` arrives, the `SegmentQC.psd_stages` -- `bbmt.timefreq.psd_ladder`
on the segment, plain `scipy.signal.welch` at 65536 points on a decimation
ladder (1000 Hz, then 100 Hz; a 1-3 h window supports those two) -- are drawn
each stage over the decade its resolution suits, exactly as
`scripts/psd_qc.py` draws figure 05 for the whole record.

Two panels stacked on one frequency axis, one per impedance pair (`PANELS`):
"By-Ex (Zxy)" on top with By blue and Ex red, "Bx-Ey (Zyx)" below with Bx
blue and Ey red, the remote's coil of the same component in grey underneath
when a remote is in. One log-log axis each, "PSD (units^2/Hz)", with the
units per curve in the legend. Faint green dashed lines mark the Schumann
resonances and faint orange ones 50 Hz and its harmonics up to Nyquist,
labelled once, on the top panel. The view starts at the extent of the data
and cannot be zoomed or panned out past it.

Nothing is computed here, and nothing is produced: the whole-record figure
05 still comes from `psd_qc.py`, run from the Process tab. What to read off
these plots is not written on the tab (Ben, 2026-09-22): that goes in the
students' PDF, not in a paragraph nobody reads twice.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bbmt.timefreq import UNIT
from bbmt_gui import theme
from bbmt_gui.plots import share_x_axis
from bbmt_gui.qc_plots import PLACEHOLDER, draw_psd, psd_plot, window_title

# (title, (magnetic, electric)) top to bottom -- the MATLAB app's Welch tab
PANELS = (
    ("By-Ex (Zxy)", ("hy", "ex")),
    ("Bx-Ey (Zyx)", ("hx", "ey")),
)


def legend_name(comp: str, qc) -> str:
    """'By  (nT)^2/Hz, scalar gain', 'Ex  (mV/km)^2/Hz', 'rBy E08  (nT)^2/Hz, scalar gain'."""
    unit = UNIT.get(comp.removeprefix("r_"), "")
    name = theme.label(comp) + (f" {qc.remote}" if comp.startswith("r_") and qc.remote else "")
    gain = ", scalar gain" if comp in getattr(qc, "scalar_only", ()) else ""
    return f"{name}  ({unit})²/Hz{gain}"


class SpectraTab(QWidget):
    """Two log-log PSD panels of the loaded window, redrawn on `qc_ready`."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.qc = None

        self.title_label = QLabel(PLACEHOLDER, self)
        self.title_label.setStyleSheet("font-weight: bold")

        self.plots = {}
        panels = QVBoxLayout()
        panels.setSpacing(0)
        for title, _comps in PANELS:
            plot = psd_plot(self, title)
            if self.plots:
                plot.setXLink(next(iter(self.plots.values())))
            self.plots[title] = plot
            panels.addWidget(plot)
        share_x_axis(list(self.plots.values()))
        for plot in list(self.plots.values())[:-1]:
            plot.getAxis("bottom").showLabel(False)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addLayout(panels, 1)

        store = self.state.segment_store
        store.qc_started.connect(self._started)
        store.qc_ready.connect(self.draw)
        store.qc_failed.connect(lambda m: self.title_label.setText(f"QC failed: {m}"))
        self.state.selection_changed.connect(self._selection_changed)

    def reload(self) -> None:
        self.clear()

    def clear(self) -> None:
        self.qc = None
        for plot in self.plots.values():
            plot.clear()
        self.title_label.setText(PLACEHOLDER)

    def _selection_changed(self, selection) -> None:
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        # keep what is in view until the new result replaces it (a remote
        # change must not blank the tab)
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    def draw(self, qc) -> None:
        """Each pair's two channels, the remote's coil of the magnetic one under them."""
        self.qc = qc
        for k, (title, (b, e)) in enumerate(PANELS):
            curves = [(comp, legend_name(comp, qc)) for comp in (b, e, "r_" + b)]
            draw_psd(self.plots[title], qc.psd_stages, curves, labelled=(k == 0))
        rates = ", ".join(f"{fs:g}" for fs, _f, _p in qc.psd_stages)
        self.title_label.setText(f"{window_title(qc)}  -  PSD stages at {rates} Hz")
