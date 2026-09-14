"""SiteMap and PairSummary: the Process tab's map and the summary beside the pair.

`SiteMap` is borrowed from the MATLAB app's `UpdateMap`; `PairSummary`, below,
is its Process Data tab's summary text (distance, overlap, window length,
recommended remote), the map's kilometres beside the window bar's hours.

`docs/matlab_app_borrowing.md` says what the map is and is not: an offline plain
lat/lon scatter of every site with a position in `survey.yaml`, the station
green, the remote blue, a stack's members orange, everything else grey, each
dot with a dark outline. No network and no `geoaxes`: the **basemap** under
the dots is `<workspace>/basemap.png`, which `scripts/fetch_basemap.py` (the
"Fetch basemap" button, `basemap_argv`) fetched once, already warped onto
this same lon/lat grid; the map only draws it, as a `pg.ImageItem` over the
extent in `basemap.json`, with the provider's attribution in the corner, and
reloads it when a fetch_basemap job finishes. Without it a grey line says
how to get one. Under the map the one number it exists for -- "remote E08 at
148.6 km", from `bbmt.survey.distance_km`.

Nothing here computes a product: the geometry is a haversine and a scatter.
Real longitude is the x axis and real latitude the y axis; the local map
scale comes from locking the ViewBox's aspect ratio to cos(mean latitude) --
one degree of longitude covers less ground than one degree of latitude away
from the equator, and pyqtgraph's `setAspectLocked(True, ratio=r)` makes one
x unit take r pixels for every one y unit's pixel (`ViewBox.setAspectLocked`,
pyqtgraph 0.14), so `r = cos(mean latitude)` draws the map at true relative
scale without pre-scaling the coordinates themselves.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from bbmt.survey import distance_km
from bbmt_gui.theme import (
    FOREGROUND, IDLE_COLOUR, OK_COLOUR, PAIR_REMOTE_COLOUR, SITE_OUTLINE, SUMMARY_COLOUR, SURFACE,
    WARN_COLOUR,
)
from bbmt_gui.window_bar import WindowBar, overlap

BASEMAP_SCRIPT = "fetch_basemap.py"
NO_BASEMAP = "no basemap - Fetch basemap on the Process tab (needs internet)"


def basemap_argv(state) -> list[str]:
    """`scripts/fetch_basemap.py <survey.yaml>`: what the Process tab's Fetch basemap button queues."""
    return [state.python_exe, state.script(BASEMAP_SCRIPT), str(state.survey_yaml)]


class SiteMap(QWidget):
    """Every positioned site as a dot, the station/remote/members coloured, over the basemap if fetched."""

    # the role colours, from `theme` (the window bar draws its two spans in the same two)
    GREY, STATION, REMOTE, MEMBER = IDLE_COLOUR, OK_COLOUR, PAIR_REMOTE_COLOUR, WARN_COLOUR
    SIZES = {GREY: 6, STATION: 14, REMOTE: 11, MEMBER: 10}

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.positions: dict[str, tuple[float, float]] = {}
        self.latlon: dict[str, tuple[float, float]] = {}
        self.colours: dict[str, str] = {}
        self.roles: tuple = (None, None, [])

        self.plot = pg.PlotWidget(parent=self)
        self.plot.setMinimumHeight(190)
        self.plot.setAspectLocked(True)  # reload() sets the true ratio once sites are known
        self.plot.setLabel("left", "latitude (deg)")
        self.plot.setLabel("bottom", "longitude (deg)")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        for side in ("left", "bottom"):
            self.plot.getAxis(side).enableAutoSIPrefix(False)
        self.scatter = pg.ScatterPlotItem(pen=pg.mkPen(SITE_OUTLINE, width=1.5))  # reads on imagery
        self.plot.addItem(self.scatter)
        self.texts: list[pg.TextItem] = []
        self.basemap_item: pg.ImageItem | None = None
        self.attribution_item: pg.TextItem | None = None
        self.basemap_info: dict | None = None
        self.basemap_label = QLabel(NO_BASEMAP, self)
        self.basemap_label.setStyleSheet(f"color: {IDLE_COLOUR}; font-size: 8pt")
        self.distance_label = QLabel("no survey loaded", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.basemap_label)
        layout.addWidget(self.distance_label)
        state.runner.job_finished.connect(self._job_finished)

    def reload(self) -> None:
        """Rebuild from `survey.yaml`: every site that declares a latitude and a longitude."""
        for text in self.texts:
            self.plot.removeItem(text)
        self.texts.clear()
        self.positions.clear()
        self.latlon.clear()
        self.colours.clear()
        survey = self.state.survey
        self.load_basemap()
        if survey is None:
            self.scatter.setData([])
            self.distance_label.setText("no survey loaded")
            return
        sites = {}
        for name in self.state.configured_sites():
            cfg = survey.site(name)
            if cfg.latitude is not None and cfg.longitude is not None:
                sites[name] = (float(cfg.latitude), float(cfg.longitude))
        if sites:
            mean_lat = sum(lat for lat, _lon in sites.values()) / len(sites)
            self.plot.getViewBox().setAspectLocked(True, ratio=math.cos(math.radians(mean_lat)))
            for name, (lat, lon) in sites.items():
                self.latlon[name] = (lat, lon)
                self.positions[name] = (lon, lat)
                self.colours[name] = self.GREY
        font = QFont()
        font.setPointSize(7)
        for name, (x, y) in self.positions.items():
            text = pg.TextItem(name, color=FOREGROUND, anchor=(0.0, 1.0))
            text.setFont(font)
            text.setPos(x, y)
            self.plot.addItem(text)
            self.texts.append(text)
        self.set_roles(*self.roles)

    def set_roles(self, station: str | None, remote: str | None, members=()) -> None:
        """Colour the dots: station green and larger, remote blue, stack members orange."""
        members = [m for m in (members or []) if m in self.positions]
        self.roles = (station, remote, list(members))
        for name in self.colours:
            self.colours[name] = self.GREY
        for name in members:
            self.colours[name] = self.MEMBER
        if remote in self.colours:
            self.colours[remote] = self.REMOTE
        if station in self.colours:
            self.colours[station] = self.STATION
        spots = [
            {"pos": self.positions[name], "brush": pg.mkBrush(colour),
             "size": self.SIZES[colour], "data": name}
            for name, colour in self.colours.items()
        ]
        self.scatter.setData(spots)
        self._set_distance(station, remote)

    def _set_distance(self, station, remote) -> None:
        if not remote:
            self.distance_label.setText("no remote selected")
            return
        if station not in self.latlon or remote not in self.latlon:
            missing = station if station not in self.latlon else remote
            self.distance_label.setText(f"remote {remote}: {missing} has no position in survey.yaml")
            return
        km = distance_km(*self.latlon[station], *self.latlon[remote])
        self.distance_label.setText(f"remote {remote} at {km:.1f} km")

    # ------------------------------------------------------------ the basemap

    def load_basemap(self) -> None:
        """Draw `<workspace>/basemap.png` under the dots over `basemap.json`'s extent, or say so."""
        for item in (self.basemap_item, self.attribution_item):
            if item is not None:
                self.plot.removeItem(item)
        self.basemap_item = self.attribution_item = self.basemap_info = None
        survey = self.state.survey
        png = survey.workspace / "basemap.png" if survey is not None else None
        meta = png.with_suffix(".json") if png is not None else None
        if png is None or not png.exists() or not meta.exists():
            self.basemap_label.setText(NO_BASEMAP)
            self.basemap_label.show()
            return
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            with Image.open(png) as image:
                rgb = np.asarray(image.convert("RGB"))
            w, e, s, n = (float(info[k]) for k in ("lon_min", "lon_max", "lat_min", "lat_max"))
        except (OSError, ValueError, KeyError) as exc:
            self.basemap_label.setText(f"basemap unreadable ({exc}) - Fetch basemap again")
            self.basemap_label.show()
            return
        # the PNG's first row is north; pyqtgraph puts row 0 at the rect's
        # smallest y, which on this y-up view is the south edge: flip the rows
        item = pg.ImageItem(axisOrder="row-major")
        item.setImage(np.ascontiguousarray(rgb[::-1]), autoLevels=False, levels=(0, 255))
        item.setRect(QRectF(w, s, e - w, n - s))
        item.setZValue(-100)  # under the dots and their names
        self.plot.addItem(item)
        font = QFont()
        font.setPointSize(6)
        text = pg.TextItem(str(info.get("attribution", "")).replace("(C)", "\u00a9"), color=FOREGROUND,
                           anchor=(1.0, 1.0), fill=pg.mkBrush(SURFACE))
        text.setFont(font)
        text.setPos(e, s)
        text.setZValue(-50)
        self.plot.addItem(text)
        self.basemap_item, self.attribution_item, self.basemap_info = item, text, info
        self.basemap_label.hide()

    def _job_finished(self, index: int, ok: bool) -> None:
        """A fetch_basemap job that succeeded: draw what it wrote."""
        job = self.state.runner.jobs[index]
        if ok and any(Path(arg).name == BASEMAP_SCRIPT for arg in job.argv):
            self.load_basemap()

    def distance_km(self, station, remote) -> float | None:
        """The separation the label reports, or None when either site has no position."""
        if station not in self.latlon or remote not in self.latlon:
            return None
        return distance_km(*self.latlon[station], *self.latlon[remote])


# ------------------------------------------------------------- the summary


def hours_text(hours: float) -> str:
    """'41.3 h (1.72 days)': the days from one day up, as the MATLAB summary reads."""
    return f"{hours:.1f} h" + (f" ({hours / 24:.2f} days)" if hours >= 24 else "")


class PairSummary(QWidget):
    """Row 1 of the Process tab: distance, overlap, window length and the recommended remote.

    The kilometres are the map's (`SiteMap.distance_km`, None for a site with
    no position, such as a stack) and every hour comes from the window bar's
    recorded spans (`WindowBar.span`, read through its one queue). The
    recommendation is the station's declared `remote:` when it has a usable
    one, otherwise the raw site whose recorded span overlaps the station's
    longest. **Tie-break rule** (Ben, 2026-09-23): with no declared remote,
    more than one candidate can tie on overlap hours -- for E08, nine raw
    sites cover its whole archive -- so any candidate within 1 h of the
    longest overlap is treated as tied, and among the tied candidates the
    NEAREST one (`SiteMap.distance_km`) wins; a candidate with no declared
    position (so no distance) sorts last, and a further tie goes to the first
    by name. Picking another remote, a stack included, never changes it.
    The candidates' spans (every raw site's) are only asked for while the
    summary is on screen, so a hidden Process tab never delays the tree or the
    segment store behind 59 span reads.
    """

    def __init__(self, state, site_map: SiteMap, bar: WindowBar, parent=None):
        super().__init__(parent)
        self.state, self.site_map, self.bar = state, site_map, bar
        self.distance, self.overlap, self.length, self.recommended = (QLabel(self) for _ in range(4))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        for label in (self.distance, self.overlap, self.length, self.recommended):
            colour = OK_COLOUR if label is self.recommended else SUMMARY_COLOUR
            label.setStyleSheet(f"color: {colour}; font-weight: bold")
            layout.addWidget(label)
        bar.spans_changed.connect(self.refresh)
        bar.window_changed.connect(lambda _start, _end: self.refresh())

    def hours(self, a, b) -> float | None:
        """Hours two sites' recorded spans share: None until both are read, 0.0 if they never meet."""
        span_a, span_b = self.bar.span(a), self.bar.span(b)
        if span_a is None or span_b is None:
            return None
        common = overlap(span_a, span_b)
        return 0.0 if common is None else (common[1] - common[0]).total_seconds() / 3600.0

    def km(self, a, b) -> str:
        if not a or not b:
            return "-"
        km = self.site_map.distance_km(a, b)
        return "no position" if km is None else f"{km:.1f} km"

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()  # now the spans it needs may be read

    TIE_HOURS = 1.0  # a candidate within this many hours of the longest overlap is tied on it

    def recommendation(self) -> tuple[str | None, str]:
        """(site or None, why) for the bar's station; asks the bar for the spans it needs.

        No remote declared: rank the other raw sites by hours of overlap with
        the station, treat every one within `TIE_HOURS` of the longest as
        tied, and of those tied candidates pick the nearest by
        `SiteMap.distance_km` (a candidate with no position sorts last; a
        further tie goes to the first by name).
        """
        station = self.bar.station
        if not station:
            return None, ""
        declared = self.state.default_remote(station)
        candidates = [declared] if declared else sorted(s for s in self.state.raw_sites() if s != station)
        if self.isVisible():  # a hidden summary never holds the archive lock up for its spans
            self.bar.read_spans(candidates)
        if declared:
            return declared, "the station's declared remote: in survey.yaml"
        waiting = sum(not self.bar.known(s) for s in (station, *candidates))
        if waiting:
            return None, f"reading recorded spans ({waiting} to go)"
        hours = {c: self.hours(station, c) or 0.0 for c in candidates}
        best_hours = max(hours.values(), default=0.0)
        if best_hours <= 0:
            return None, f"no raw site overlaps {station}"
        tied = [c for c in candidates if hours[c] >= best_hours - self.TIE_HOURS]

        def distance_key(name: str):
            km = self.site_map.distance_km(station, name)
            return (float("inf") if km is None else km, name)

        best = min(tied, key=distance_key)
        why = ("no remote declared; the raw site nearest the station among those within "
               f"{self.TIE_HOURS:g} h of the longest overlap ({len(tied)} tied)")
        return best, why

    def refresh(self) -> None:
        """Every line again, from the bar's pair, spans and window."""
        station, remote = self.bar.station, self.bar.remote
        self.distance.setText(f"Distance to remote: {self.km(station, remote)}")
        hours = self.hours(station, remote)
        self.overlap.setText("Overlap available: " + (
            "-" if not remote else "reading ..." if hours is None else hours_text(hours)))
        window = self.bar.window()
        length = (window[1] - window[0]).total_seconds() / 3600.0 if window else None
        self.length.setText("Window length: " + ("-" if length is None else hours_text(length)))
        site, why = self.recommendation()
        if site is None:
            text = why or "-"
        else:
            hours = self.hours(station, site)
            text = f"{site} ({self.km(station, site)}, {'...' if hours is None else f'{hours:.1f} h'})"
        self.recommended.setText(f"Recommended remote: {text}")
        self.recommended.setToolTip(why)
