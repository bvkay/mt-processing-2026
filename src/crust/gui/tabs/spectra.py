# -*- coding: utf-8 -*-
"""
Spectra tab

Shows the loaded window's PSDs in two panels, By-Ex (Zxy) over Bx-Ey (Zyx).
On the store's `qc_ready` the tab draws `SegmentQC.psd_stages`
(`crust.timefreq.psd_ladder` on the segment: `scipy.signal.welch` at 65536
points on a decimation ladder of 1000 Hz then 100 Hz, the two stages a
1-3 h window supports) for the window chosen on the Time Series tab. Each
stage is drawn over the decade its resolution suits, as `scripts/psd_qc.py`
draws figure 05 for the whole record.

Two panels share one frequency axis, one per impedance pair (`PANELS`):
"By-Ex (Zxy)" on top with By blue and Ex red, and "Bx-Ey (Zyx)" below with
Bx blue and Ey red. With a remote, the remote's coil of the same component
is drawn grey underneath. Names follow the roles channels play
(`crust.gui.channels.roles`): on a LEMI-424 the panels are "By-E1 (Zxy)"
and "Bx-E2 (Zyx)", with the first two electrics in the roles of Ex and Ey.
Each panel has one log-log axis, "PSD (units^2/Hz)", with each curve's units
in the legend. Faint green dashed lines mark the Schumann resonances and
faint orange ones 50 Hz and its harmonics up to Nyquist, labelled once on
the top panel. The view starts at the extent of the data and cannot be
zoomed or panned out past it.

The whole-record figure 05 comes from `scripts/psd_qc.py`.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from crust.gui import channels, theme
from crust.gui.plots import share_x_axis
from crust.gui.qc_plots import PLACEHOLDER, draw_psd, psd_plot, window_title

# (title, (magnetic, electric)) top to bottom, in
# the LEMI-423 role names (`panel`); the titles key the plots
PANELS = (
    ("By-Ex (Zxy)", ("hy", "ex")),
    ("Bx-Ey (Zyx)", ("hx", "ey")),
)


def panel(key: str, local: dict, remote: dict | None = None) -> tuple[str, list[str]]:
    """Resolve a `PANELS` entry for a record's channel roles.

    Args:
        key (str): The panel title in `PANELS`.
        local (dict): Local roles from `channels.roles`.
        remote (dict | None): Remote roles from `channels.roles`.

    Returns:
        tuple[str, list[str]]: The panel title for the record and the
        channels present (magnetic, electric, remote magnetic), e.g.
        ("By-Ex (Zxy)", ["hy", "ex", "r_hy"]) on a LEMI-423 with a remote,
        ("By-E1 (Zxy)", ["by", "e1"]) on a LEMI-424 without one.
    """
    b, e = dict(PANELS)[key]
    title = channels.title(f"{{{b}}}-{{{e}}}" + key[key.index(" "):], local)
    comps = [channels.resolve(c, local, remote) for c in (b, e, "r_" + b)]
    return title, [c for c in comps if c]


def legend_name(comp: str, qc) -> str:
    """Return a channel's legend entry, e.g. 'By  (nT)^2/Hz, scalar gain', 'Ex  (mV/km)^2/Hz' or 'rBy S02  (nT)^2/Hz'."""
    unit = channels.unit(comp)
    name = theme.label(comp) + (f" {qc.remote}" if comp.startswith("r_") and qc.remote else "")
    gain = ", scalar gain" if comp in getattr(qc, "scalar_only", ()) else ""
    return f"{name}  ({unit})²/Hz{gain}"


class SpectraTab(QWidget):
    """Two log-log PSD panels of the loaded window, redrawn on `qc_ready`.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

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
        """Clear the panels after a survey change."""
        self.clear()

    def clear(self) -> None:
        """Clear the panels and the title."""
        self.qc = None
        for plot in self.plots.values():
            plot.clear()
        self.title_label.setText(PLACEHOLDER)

    def _selection_changed(self, selection) -> None:
        """Clear the panels when nothing is selected."""
        if selection is None:
            self.clear()

    def _started(self, what: str) -> None:
        """Show that a QC is running; the panels keep the previous result until it is replaced."""
        self.title_label.setText(f"computing {what}... (showing the previous result until it is done)")

    def draw(self, qc) -> None:
        """Draw each pair's two channels, with the remote's matching coil underneath."""
        self.qc = qc
        for k, (key, _pair) in enumerate(PANELS):
            title, comps = panel(key, qc.roles, qc.remote_roles)
            self.plots[key].setTitle(title, color=theme.TEXT)
            curves = [(comp, legend_name(comp, qc)) for comp in comps]
            draw_psd(self.plots[key], qc.psd_stages, curves, labelled=(k == 0))
        rates = ", ".join(f"{fs:g}" for fs, _f, _p in qc.psd_stages)
        self.title_label.setText(f"{window_title(qc)}  -  PSD stages at {rates} Hz")
