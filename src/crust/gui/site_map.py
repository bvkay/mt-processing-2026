# -*- coding: utf-8 -*-
"""
Site map and pair summary of the Process tab

`SiteMap` is the map of the sites, and `PairSummary` the Process tab's
summary text (distance, overlap, window length, recommended remote),
combining the map's kilometres with the window bar's hours.

The map is an offline lat/lon scatter of every site with a position in
`survey.yaml`: station green, remote blue, stack members orange, the rest
grey, each dot outlined dark and each name on a translucent dark box. It is
drawn over `<workspace>/basemap.png`, which `scripts/fetch_basemap.py` fetches
once, already warped onto this grid; `fetch_basemap_if_missing` runs the
script when a survey is opened without a `basemap.json`. The map draws the PNG
as a `pg.ImageItem` over the JSON's extent and reloads it when a fetch
finishes. The provider and attribution required by the tile terms are shown in
the map's tooltip; a grey line below the map appears only when there is no
basemap. The view cannot zoom or pan out past the basemap, or, without one,
past the sites' extent padded as the script pads it; zooming in is
unrestricted. Below the map a label reads, e.g., "remote S02 at 148.6 km".

Distances are haversine distances (`crust.survey.distance_km`). Longitude
is x and latitude y, and the ViewBox aspect is locked to cos(mean latitude)
(`setAspectLocked(True, ratio=r)` gives one x unit r pixels for each y
unit's pixel in pyqtgraph 0.14), so the map is at true relative scale
without rescaling the coordinates.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PIL import Image
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from crust.survey import distance_km
from crust.gui.jobs import QUEUED, RUNNING
from crust.gui.theme import (
    FOREGROUND, IDLE_COLOUR, OK_COLOUR, PAIR_REMOTE_COLOUR, SITE_LABEL_ALPHA, SITE_OUTLINE,
    SUMMARY_COLOUR, SURFACE, WARN_COLOUR,
)
from crust.gui.window_bar import WindowBar, overlap

BASEMAP_SCRIPT = "fetch_basemap.py"
NO_BASEMAP = "no basemap: fetched on survey open when online (see the console strip)"
MARGIN, MIN_PAD_DEG = 0.15, 0.1  # scripts/fetch_basemap.py's padding of the sites' extent


def attribution_text(info: dict) -> str:
    """Return the map's tooltip for a basemap.json: provider, then attribution, with "(C)" as the sign."""
    return f"Basemap: {info.get('provider', '')} - " + str(info.get("attribution", "")).replace(
        "(C)", "\N{COPYRIGHT SIGN}")


def fetch_basemap_if_missing(state) -> int | None:
    """Run scripts/fetch_basemap.py when the open survey has no `<workspace>/basemap.json`.

    The job opens no archive, so like New survey it starts immediately
    through `JobRunner.run_now`. Offline it fails within its 30 s tile
    timeout and the console strip shows why; the next attempt is at the next
    survey open.

    Args:
        state: The shared `crust.gui.app.State`.

    Returns:
        int | None: The job's index, or None when a basemap exists or a
        fetch for this survey is already queued or running.
    """
    survey = state.survey
    if survey is None or (survey.workspace / "basemap.json").exists():
        return None
    argv = [state.python_exe, state.script(BASEMAP_SCRIPT), str(state.survey_yaml)]
    if any(job.argv == argv and job.status in (QUEUED, RUNNING) for job in state.runner.jobs):
        return None
    return state.runner.run_now("fetch_basemap (needs internet)", argv)


class SiteMap(QWidget):
    """Map of every positioned site, with the station, remote and stack members coloured.

    Args:
        state: The shared `crust.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

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
        self.basemap_info: dict | None = None
        self.basemap_label = QLabel(NO_BASEMAP, self, wordWrap=True)  # shown only with no basemap
        self.basemap_label.setStyleSheet(f"color: {IDLE_COLOUR}; font-size: 8pt")
        self.distance_label = QLabel("no survey loaded", self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.basemap_label)
        layout.addWidget(self.distance_label)
        state.runner.job_finished.connect(self._job_finished)

    def reload(self) -> None:
        """Rebuild from `survey.yaml`, plotting every site that declares a latitude and a longitude."""
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
        box = QColor(SURFACE)
        box.setAlpha(SITE_LABEL_ALPHA)
        for name, (x, y) in self.positions.items():
            text = pg.TextItem(name, color=FOREGROUND, anchor=(0.0, 1.0), fill=pg.mkBrush(box))
            text.setFont(font)
            text.setPos(x, y)
            text.setZValue(-10)  # over the basemap, under the dots, so a name does not hide a site
            self.plot.addItem(text)
            self.texts.append(text)
        self.set_roles(*self.roles)
        self.lock_extent()

    def extent(self) -> tuple[float, float, float, float] | None:
        """Return (west, east, south, north): the basemap's extent, else the sites' padded as fetch_basemap.py pads."""
        if self.basemap_info is not None:
            return tuple(float(self.basemap_info[k]) for k in ("lon_min", "lon_max", "lat_min", "lat_max"))
        if not self.positions:
            return None
        (w, e), (s, n) = ((min(v), max(v)) for v in zip(*self.positions.values()))
        pad_x, pad_y = max(MARGIN * (e - w), MIN_PAD_DEG), max(MARGIN * (n - s), MIN_PAD_DEG)
        return w - pad_x, e + pad_x, s - pad_y, n + pad_y

    def lock_extent(self) -> None:
        """Show the whole extent and prevent zooming or panning out past it; the aspect lock stays."""
        extent, box = self.extent(), self.plot.getViewBox()
        if extent is None:  # nothing to show: no limits left over from the last survey
            box.setLimits(xMin=None, xMax=None, yMin=None, yMax=None, maxXRange=None, maxYRange=None)
            return
        w, e, s, n = extent
        box.setLimits(xMin=w, xMax=e, yMin=s, yMax=n, maxXRange=e - w, maxYRange=n - s)
        box.setRange(xRange=(w, e), yRange=(s, n), padding=0)

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
        """Show the station-remote distance below the map."""
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
        """Draw `<workspace>/basemap.png` under the dots over `basemap.json`'s extent, or show why not."""
        if self.basemap_item is not None:
            self.plot.removeItem(self.basemap_item)
        self.basemap_item = self.basemap_info = None
        survey = self.state.survey
        png = survey.workspace / "basemap.png" if survey is not None else None
        meta = png.with_suffix(".json") if png is not None else None
        self.plot.setToolTip("")
        self.basemap_label.setVisible(True)
        if png is None or not png.exists() or not meta.exists():
            self.basemap_label.setText(NO_BASEMAP)
            return
        try:
            info = json.loads(meta.read_text(encoding="utf-8"))
            with Image.open(png) as image:
                rgb = np.asarray(image.convert("RGB"))
            w, e, s, n = (float(info[k]) for k in ("lon_min", "lon_max", "lat_min", "lat_max"))
        except (OSError, ValueError, KeyError) as exc:
            self.basemap_label.setText(f"basemap unreadable ({exc}) - delete {meta.name} and reopen the survey")
            return
        # the PNG's first row is north; pyqtgraph puts row 0 at the rect's
        # smallest y, which on this y-up view is the south edge: flip the rows
        item = pg.ImageItem(axisOrder="row-major")
        item.setImage(np.ascontiguousarray(rgb[::-1]), autoLevels=False, levels=(0, 255))
        item.setRect(QRectF(w, s, e - w, n - s))
        item.setZValue(-100)  # under the dots and their names
        self.plot.addItem(item)
        self.basemap_item, self.basemap_info = item, info
        self.plot.setToolTip(attribution_text(info))  # the credit the tile terms require
        self.basemap_label.setVisible(False)
        self.lock_extent()

    def _job_finished(self, index: int, ok: bool) -> None:
        """Load the basemap after a successful fetch_basemap job."""
        job = self.state.runner.jobs[index]
        if ok and any(Path(arg).name == BASEMAP_SCRIPT for arg in job.argv):
            self.load_basemap()

    def distance_km(self, station, remote) -> float | None:
        """Return the distance in km between two sites, or None when either has no position."""
        if station not in self.latlon or remote not in self.latlon:
            return None
        return distance_km(*self.latlon[station], *self.latlon[remote])


# ------------------------------------------------------------- the summary


def hours_text(hours: float) -> str:
    """Format hours as '41.3 h', adding days from one day up, e.g. '41.3 h (1.72 days)'."""
    return f"{hours:.1f} h" + (f" ({hours / 24:.2f} days)" if hours >= 24 else "")


class PairSummary(QWidget):
    """Summary in row 1 of the Process tab: distance, overlap, window length and recommended remote.

    Distances come from the map (`SiteMap.distance_km`; None for a site with
    no position, such as a stack) and hours from the window bar's recorded
    spans (`WindowBar.span`). The recommended remote is the station's
    declared `remote:`, else a raw site chosen by `recommendation`; it does
    not change when another remote is picked. Spans are requested only while
    the summary is visible, so a hidden Process tab does not delay the tree
    or the segment store.

    Args:
        state: The shared `crust.gui.app.State`.
        site_map (SiteMap): The Process tab's map.
        bar (WindowBar): The Process tab's window bar.
        parent (QWidget | None): Qt parent.
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
        """Return the hours two sites' recorded spans share; None until both are read, 0.0 if they do not meet."""
        span_a, span_b = self.bar.span(a), self.bar.span(b)
        if span_a is None or span_b is None:
            return None
        common = overlap(span_a, span_b)
        return 0.0 if common is None else (common[1] - common[0]).total_seconds() / 3600.0

    def km(self, a, b) -> str:
        """Return the distance between two sites as text, "-" or "no position"."""
        if not a or not b:
            return "-"
        km = self.site_map.distance_km(a, b)
        return "no position" if km is None else f"{km:.1f} km"

    def showEvent(self, event) -> None:
        """Refresh on show, when the spans may be read."""
        super().showEvent(event)
        self.refresh()

    # a candidate whose overlap covers at least this fraction of the station's own
    # record qualifies, and the nearest qualifying site is recommended; a distant
    # remote (hundreds of km away) can lack coherent signal at broadband periods
    # where an adjacent site does not. With no qualifying site the longest overlap
    # wins, nearest among those within TIE_HOURS of it.
    ENOUGH_FRACTION = 0.5
    TIE_HOURS = 1.0

    def recommendation(self) -> tuple[str | None, str]:
        """Recommend a remote for the bar's station, requesting the spans it needs.

        The station's declared remote is used when there is one. Otherwise
        the recommendation is the nearest raw site (by `SiteMap.distance_km`;
        sites without a position sort last, then by name) among those whose
        overlap covers at least `ENOUGH_FRACTION` of the station's own record,
        or, failing that, the nearest among those within `TIE_HOURS` of the
        longest overlap.

        Returns:
            tuple[str | None, str]: The site, or None, and the reason.
        """
        station = self.bar.station
        if not station:
            return None, ""
        declared = self.state.default_remote(station)
        candidates = [declared] if declared else sorted(s for s in self.state.raw_sites() if s != station)
        if self.isVisible():  # spans are read only while the summary is visible
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

        def distance_key(name: str):
            km = self.site_map.distance_km(station, name)
            return (float("inf") if km is None else km, name)

        span = self.bar.span(station)
        own_hours = (span[1] - span[0]).total_seconds() / 3600.0 if span else best_hours
        enough = [c for c in candidates if hours[c] >= self.ENOUGH_FRACTION * own_hours]
        if enough:
            best = min(enough, key=distance_key)
            why = (f"no remote declared; the nearest raw site among the {len(enough)} whose overlap "
                   f"covers at least {self.ENOUGH_FRACTION:.0%} of {station}'s record")
            return best, why
        tied = [c for c in candidates if hours[c] >= best_hours - self.TIE_HOURS]
        best = min(tied, key=distance_key)
        why = (f"no remote declared and no raw site overlaps {self.ENOUGH_FRACTION:.0%} of "
               f"{station}'s record; the nearest of the {len(tied)} with the longest overlap")
        return best, why

    def refresh(self) -> None:
        """Redraw every line from the bar's pair, spans and window."""
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
