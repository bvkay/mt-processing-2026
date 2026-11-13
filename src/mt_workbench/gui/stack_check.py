# -*- coding: utf-8 -*-
"""
Member check and stack preview for the Stacks tab

`MemberCheck` reads a recipe's members on a bounded span of the loaded
window (`mt_workbench.stackcheck.check_span`), runs
`mt_workbench.stackcheck.compute_check` on them off the GUI thread, and
shows the result: a table of each member channel's squared coherence with
the mean of the others per band (median and 10th percentile over the
usable chunks), its polarity correlation and its flags; a bar plot of the
full-band coherence, each bar in its field's colour and a flagged one drawn
hollow with a red outline and its flags above it (electrics and BAD_COLOUR
are both red, so a flag is told by shape); the stack's band power over the
members' on the Spectra tab's two pair panels, "By-Ex (Zxy)" over "Bx-Ey
(Zyx)" as on that tab; and, for a coherence-weighted time stack, the
weights over time, each channel in its field's colour, the members told
apart by opacity and the legend. The weight axis reads plain weights from
0; the legend holds one row per channel (up to `LEGEND_MAX_COLUMNS`
members a row) in a translucent box at the plot's top, and the axis top is
raised so the largest weight lies under it.

Reads follow the archive lock (`mt_workbench.gui.reader.ArchiveLock`): one
member per `_MemberRead` thread, the lock taken before the thread starts
and released once that member's archive is closed, so a tree click waits
for one member's read at most (0.47-0.61 s for 1 h of two channels at
1000 Hz, measured). Each member is read from the archive
processing would read (`State.processing_archive`: the filtered variant
when it is built and current, else the raw archive, which the note says);
no variant is built. The read arrays are kept per site with the span, the
roles, `use_filters` and the archive's stamp (path, mtime, size, by stat),
so a changed member set reads only the new sites. `clear()` drops them;
the tab calls it when it is hidden and when the survey changes, since
memory limits the batches that run beside the GUI (16 members of two
channels at 3.6 M float32 samples hold 461 MB).

The plots are live pyqtgraph views.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from mt_workbench import intersite, stackcheck, virtual
from mt_workbench.ingest import variant_path
from mt_workbench.gui import channels, segment, theme
from mt_workbench.gui.qc_plots import psd_plot
from mt_workbench.gui.reader import ReadThread
from mt_workbench.gui.tabs.spectra import PANELS
from mt_workbench.gui.window_bar import to_utc

# the archive names a role may carry: the stored names first, then those of a LEMI-424 archive built before
# docs/workbench_issues.md 92 (the reader's bx by e1 e2)
ALTERNATIVE = {"hx": "bx", "hy": "by", "ex": "e1", "ey": "e2"}
IDLE_TEXT = "no check yet: choose a recipe and load a window"
# the weights plot: a weight axis of three or more ticks under the legend's rows
WEIGHTS_MIN_HEIGHT = 160
LEGEND_MAX_COLUMNS = 8  # members a legend row holds; more members wrap each channel onto further rows
LEGEND_OFFSET = (10, 4)  # px from the weights plot's top left corner
LEGEND_GAP = 4  # px between the legend's lower edge and the largest weight
LEGEND_BRUSH = (31, 31, 31, 170)  # SURFACE, translucent: a curve under the legend shows through


def _comps(roles) -> list[str]:
    """Return the channel names to read for `roles`, in both readers' names."""
    return [c for r in roles for c in (r, ALTERNATIVE.get(r, r))]


class _MemberRead(QThread):
    """Read one member's channels on the span, off the GUI thread.

    Emits `loaded` once the member's archive is closed again, then `result`
    with ``{"arrays", "gaps", "t0", "n", "fs", "path", "variant"}`` or
    `failed` with the reason, each with the request's tag.
    """

    loaded = Signal()
    result = Signal(object, object)  # (tag, payload)
    failed = Signal(object, str)  # (tag, message)

    def __init__(self, tag, state, site, span, roles, use_filters, parent=None):
        super().__init__(parent)
        self.tag, self.state, self.site, self.span = tag, state, site, span
        self.roles, self.use_filters = tuple(roles), use_filters
        self.survey_name = state.survey.name

    def run(self) -> None:
        """Find the member's processing archive, read its roles on the span, release, report."""
        try:
            path, variant = self.state.processing_archive(self.site, self.use_filters)
            seg = segment.load_segment(path, self.survey_name, self.site, self.span[0], self.span[1],
                                       comps=_comps(self.roles))
        except Exception as exc:  # outside the record, no run, a busy or missing archive
            self.loaded.emit()
            self.failed.emit(self.tag, f"{type(exc).__name__}: {exc}")
            return
        self.loaded.emit()
        mapping = channels.roles(seg.arrays)
        missing = [r for r in self.roles if r not in mapping]
        if missing:
            self.failed.emit(self.tag, f"no {', '.join(missing)} channel in {path.name}")
            return
        self.result.emit(self.tag, {"arrays": {r: seg.arrays[mapping[r]] for r in self.roles},
                                    "gaps": list(seg.gaps), "t0": seg.t0, "n": seg.n,
                                    "fs": float(seg.sample_rate), "path": path, "variant": variant})


def _run_check(arrays, gaps, request, skipped, notes):
    """Run compute_check for a request, then set its span and add the widget's skipped sites and notes."""
    res = stackcheck.compute_check(arrays, gaps, request["fs"], request["roles"], request["engine"],
                                   request["stack"], request["weighting"], request["reject_factor"],
                                   request["min_members"])
    res.span = request["span"]
    res.skipped = list(skipped) + list(res.skipped)
    res.note = "; ".join([n for n in notes + [res.note] if n])
    return res


class MemberCheck(QWidget):
    """Reads a recipe's members on a bounded span and shows their check and the stack preview.

    Args:
        state: The shared `mt_workbench.gui.app.State`.
        parent (QWidget | None): Qt parent.
    """

    started = Signal(str)  # "reading P4S2 (2 of 8)...", "checking 8 members..."
    ready = Signal(object)  # CheckResult
    failed = Signal(str)

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self._serial = 0  # the latest request: a computed result of an older one is dropped
        self._generation = 0  # bumped by clear(): a read in flight from before it is not kept
        self._pending: dict | None = None
        self._kept: dict[str, tuple] = {}  # site -> (key, payload)
        self._unread: dict[str, tuple] = {}  # site -> (key, reason): not retried until the key changes
        self._thread: QThread | None = None
        self._result = None
        self._build()
        state.archive_lock.changed.connect(self._kick)

    # ------------------------------------------------------------ layout

    def _build(self) -> None:
        self.status = QLabel(IDLE_TEXT, self)
        self.status.setWordWrap(True)
        self.table = QTableWidget(0, 0, self)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.bars = pg.PlotWidget(parent=self)
        self.bars.setLabel("left", "γ² full band")
        self.bars.showGrid(y=True, alpha=theme.GRID_ALPHA)
        self.bars.setMouseEnabled(x=False, y=False)
        self.panels = [psd_plot(self, title) for title, _roles in PANELS]
        self.panels[1].setXLink(self.panels[0])
        self.weights = pg.PlotWidget(parent=self, axisItems={"bottom": pg.DateAxisItem(orientation="bottom",
                                                                                       utcOffset=0)})
        self.weights.setLabel("left", "weight")
        self.weights.setLabel("bottom", "UTC")
        self.weights.setMinimumHeight(WEIGHTS_MIN_HEIGHT)
        # plain weights on the axis: the SI prefix is settled when first asked, before any curve is drawn
        self.weights.getAxis("left").enableAutoSIPrefix(False)
        self.weights.addLegend(offset=LEGEND_OFFSET, labelTextColor=theme.TEXT, brush=pg.mkBrush(*LEGEND_BRUSH),
                               colCount=LEGEND_MAX_COLUMNS)
        self.weights.hide()
        top = QHBoxLayout()
        top.addWidget(self.table, 3)
        top.addWidget(self.bars, 2)
        mid = QVBoxLayout()  # one over the other on one frequency axis, as the Spectra tab reads them
        for plot in self.panels:
            mid.addWidget(plot, 1)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(self.status)
        box.addLayout(top, 2)
        box.addLayout(mid, 3)
        box.addWidget(self.weights, 1)

    # ------------------------------------------------------------ requests

    def request(self, members, roles, span, engine: str, stack: str, weighting: str, reject_factor: float,
                min_members: int, use_filters: bool) -> None:
        """Check `members` on `span`, replacing any request not started; the latest wins.

        Args:
            members (list): Sites in the order resolve_members gives them
                (by overlap); the first `stackcheck.MAX_CHECK_MEMBERS` are read.
            roles (tuple): The channels, ("hx", "hy") or ("ex", "ey").
            span (tuple): (start, end) from `stackcheck.check_span`.
            engine (str): "band" or "time".
            stack (str): "mean" or "median".
            weighting (str | None): "none" or "coherence" (None for a band stack).
            reject_factor (float | None): The band stack's rejection
                threshold; None (a time recipe) takes intersite's default.
            min_members (int | None): Kept members a band-stack window
                needs; None takes intersite's default.
            use_filters (bool): Read the filtered variant when it is built.
        """
        if self.state.survey is None:
            return
        self._serial += 1
        members = [str(m) for m in members]
        cap = stackcheck.MAX_CHECK_MEMBERS
        roles = tuple(roles)
        span = (to_utc(span[0]), to_utc(span[1]))
        keys = {s: (span, roles, bool(use_filters), self._stamp(s, use_filters)) for s in members[:cap]}
        self._pending = {"serial": self._serial, "members": members[:cap], "over": members[cap:],
                         "roles": roles, "span": span, "engine": engine, "stack": stack,
                         "weighting": "none" if weighting is None else weighting,
                         "reject_factor": float(intersite.STACK_REJECT_FACTOR if reject_factor is None
                                                else reject_factor),
                         "min_members": int(intersite.STACK_MIN_MEMBERS if min_members is None else min_members),
                         "use_filters": bool(use_filters), "keys": keys}
        # only this request's arrays stay held, so memory is one member set at most
        for held in (self._kept, self._unread):
            for site in [s for s, (key, _v) in held.items() if keys.get(s) != key]:
                del held[site]
        self._kick()

    def _stamp(self, site: str, use_filters: bool) -> tuple:
        """Return (path, mtime_ns, size) of the raw archive and of a declared variant, by stat only."""
        survey = self.state.survey
        paths = [self.state.archive_path(site)]
        if use_filters and site in survey.site_names() and survey.site(site).filters:
            paths.append(variant_path(survey, site))
        out = []
        for p in paths:
            try:
                st = p.stat()
                out.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                out.append((str(p), None, None))
        return tuple(out)

    def _kick(self) -> None:
        """Start the next member read, or the computation once every member is held or unreadable."""
        req = self._pending
        if self._thread is not None or req is None or self.state.survey is None:
            return
        todo = [s for s in req["members"] if self._kept.get(s, (None,))[0] != req["keys"][s]
                and self._unread.get(s, (None,))[0] != req["keys"][s]]
        if todo:
            lock = self.state.archive_lock
            if lock.busy and lock.holder is not self:
                return  # `changed` calls this again
            site = todo[0]
            tag = (self._generation, site, req["keys"][site])
            thread = _MemberRead(tag, self.state, site, req["span"], req["roles"], req["use_filters"], self)
            thread.loaded.connect(lambda: self.state.archive_lock.release(self))
            thread.result.connect(self._on_read)
            thread.failed.connect(self._on_unread)
            self._start(thread)
            lock.acquire(self)
            thread.start()
            done = len(req["members"]) - len(todo) + 1
            self.started.emit(f"reading {site} ({done} of {len(req['members'])})...")
            return
        self._pending = None
        arrays, gaps, skipped, notes = self._gather(req)
        thread = ReadThread(_run_check, req["serial"], arrays, gaps, req, skipped, notes, parent=self)
        thread.result.connect(self._on_result)
        thread.failed.connect(self._on_failed)
        self._start(thread)
        thread.start()
        self.started.emit(f"checking {len(arrays)} member(s)...")

    def _start(self, thread: QThread) -> None:
        """Hold `thread` as the one in flight until it finishes."""
        thread.finished.connect(self._thread_done)
        thread.finished.connect(thread.deleteLater)
        self._thread = thread

    def _thread_done(self) -> None:
        self._thread = None
        self._kick()

    def _gather(self, req: dict) -> tuple[dict, dict, list, list]:
        """Return the held arrays on one grid, their gaps, the skipped sites and notes for a request."""
        arrays, gaps, skipped, notes, ref = {}, {}, [], [], None
        for site in req["members"]:
            if self._unread.get(site, (None,))[0] == req["keys"][site]:
                skipped.append((site, f"not read: {self._unread[site][1]}"))
                continue
            payload = self._kept[site][1]
            if ref is None:
                ref = (site, payload)
            elif (payload["fs"] != ref[1]["fs"] or payload["n"] != ref[1]["n"]
                  or abs((payload["t0"] - ref[1]["t0"]).total_seconds()) * payload["fs"] > 0.5):
                skipped.append((site, f"not on {ref[0]}'s sample grid"))
                continue
            if req["use_filters"] and not payload["variant"] and self._declares_filters(site):
                notes.append(f"{site}: filtered variant not built, raw archive read")
            arrays[site], gaps[site] = payload["arrays"], payload["gaps"]
        skipped += [(s, stackcheck.OVER_CAP) for s in req["over"]]
        req["fs"] = ref[1]["fs"] if ref is not None else 1.0
        return arrays, gaps, skipped, notes

    def _declares_filters(self, site: str) -> bool:
        survey = self.state.survey
        return site in survey.site_names() and bool(survey.site(site).filters)

    def _on_read(self, tag, payload) -> None:
        generation, site, key = tag
        if generation == self._generation:
            self._kept[site] = (key, payload)
            self._unread.pop(site, None)

    def _on_unread(self, tag, message: str) -> None:
        generation, site, key = tag
        if generation == self._generation:
            self._unread[site] = (key, message)
            self._kept.pop(site, None)

    def _on_result(self, serial, result) -> None:
        if serial != self._serial:
            return
        self._result = result
        self._show(result)
        self.ready.emit(result)

    def _on_failed(self, serial, message: str) -> None:
        if serial != self._serial:
            return
        self.status.setText(f"check failed: {message}")
        self.failed.emit(message)

    def clear(self) -> None:
        """Drop the kept arrays, the result and any request not started; a result in flight is dropped on return."""
        self._generation += 1
        self._serial += 1
        self._pending = self._result = None
        self._kept.clear()
        self._unread.clear()
        self.table.setRowCount(0)
        self.bars.clear()
        for plot in self.panels:
            plot.clear()
        self.weights.clear()
        self.weights.hide()
        self.status.setText(IDLE_TEXT)

    def kept_sites(self) -> list[str]:
        """Return the sites whose arrays are held, sorted."""
        return sorted(self._kept)

    def missing(self, members, roles, span, use_filters: bool) -> list[str]:
        """Return the members a request would read: those not held for this span, roles and archive state.

        Only the first `stackcheck.MAX_CHECK_MEMBERS` count, as `request`
        reads no more. Stats only.

        Args:
            members (list): Sites, in `request`'s order.
            roles (tuple): The channels.
            span (tuple): (start, end).
            use_filters (bool): Read the filtered variants.

        Returns:
            list[str]: The sites to read, in order.
        """
        if self.state.survey is None:
            return []
        span = (to_utc(span[0]), to_utc(span[1]))
        roles = tuple(roles)
        out = []
        for site in [str(m) for m in members][:stackcheck.MAX_CHECK_MEMBERS]:
            key = (span, roles, bool(use_filters), self._stamp(site, use_filters))
            if self._kept.get(site, (None,))[0] != key:
                out.append(site)
        return out

    def result(self):
        """Return the latest CheckResult shown, or None."""
        return self._result

    def wait(self) -> None:
        """Block until the thread in flight returns, dropping any request not started; used on close."""
        self._pending = None
        if self._thread is not None:
            self._thread.wait()
        self.state.archive_lock.release(self)

    # ------------------------------------------------------------ display

    def _show(self, res) -> None:
        """Fill the status line, the table, the bars, the preview panels and the weights plot."""
        lines = [f"{len(res.members)} member(s), {res.span[0]:%Y-%m-%d %H:%M} to {res.span[1]:%H:%M} UTC, "
                 f"{res.engine} {res.stack if res.engine == 'band' else res.weighting}"]
        lines += [f"{site}: {reason}" for site, reason in res.skipped]
        if res.note:
            lines.append(res.note)
        self.status.setText("\n".join(lines))
        plan = stackcheck.check_plan(res.sample_rate)
        self._fill_table(res, plan)
        self._fill_bars(res, plan)
        self._fill_preview(res)
        self._fill_weights(res)

    def _fill_table(self, res, plan: dict) -> None:
        heads = ["member", "channel"] + [f"γ² {lo:g}-{hi:g} s" for lo, hi in plan["bands"]] + ["polarity", "flags"]
        self.table.clear()
        self.table.setColumnCount(len(heads))
        self.table.setHorizontalHeaderLabels(heads)
        for c in range(2, 2 + len(plan["bands"])):
            self.table.horizontalHeaderItem(c).setToolTip("median [10th percentile] over the chunks clear of gaps")
        rows = [(i, site, role) for role in res.roles for i, site in enumerate(res.members)]
        self.table.setRowCount(len(rows))
        bad = QBrush(QColor(theme.BAD_COLOUR))
        for r, (i, site, role) in enumerate(rows):
            cells = [site, channels.label(role)]
            for band in plan["bands"]:
                values = res.coherence.get(role, {}).get(band)
                s = stackcheck.band_summary(values[i], res.usable[role]) if values is not None else None
                cells.append("-" if s is None else f"{s[0]:.2f} [{s[1]:.2f}]")
            corr = res.polarity.get(role, np.full(len(res.members), np.nan))[i]
            cells.append("-" if not np.isfinite(corr) else f"{corr:+.2f}")
            flags = res.flags.get((site, role), [])
            cells.append(", ".join(flags))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if flags and c in (0, len(cells) - 1):
                    item.setForeground(bad)
                self.table.setItem(r, c, item)
        self.table.resizeColumnsToContents()

    def _fill_bars(self, res, plan: dict) -> None:
        """Draw each member channel's full-band gamma2 as a bar in its field's colour.

        A flagged bar is told by its shape, not its hue: BAD_COLOUR and
        E_COLOUR are both red, so on an electric recipe a red fill would not
        say which member is dead or reversed. It is drawn hollow (SURFACE)
        with a 2 px BAD_COLOUR outline, and its flags are written above it.
        """
        self.bars.clear()
        heights, brushes, pens, ticks, marks = [], [], [], [], []
        for role in res.roles:
            values = res.coherence.get(role, {}).get(plan["full_band"])
            for i, site in enumerate(res.members):
                s = stackcheck.band_summary(values[i], res.usable[role]) if values is not None else None
                height = 0.0 if s is None else float(s[0])
                flags = res.flags.get((site, role)) or []
                if flags:
                    brushes.append(pg.mkBrush(theme.SURFACE))
                    pens.append(pg.mkPen(theme.BAD_COLOUR, width=2))
                    marks.append((len(heights), height, ", ".join(flags)))
                else:
                    brushes.append(pg.mkBrush(theme.colour(role)))
                    pens.append(pg.mkPen(theme.MARKER_EDGE))
                heights.append(height)
                ticks.append((len(ticks), f"{site} {channels.label(role)}"))
        if heights:
            self.bars.addItem(pg.BarGraphItem(x=np.arange(len(heights)), height=heights, width=0.8,
                                              brushes=brushes, pens=pens))
            self.bars.getAxis("bottom").setTicks([ticks])
        for x, height, text in marks:
            label = pg.TextItem(text, color=theme.BAD_COLOUR, anchor=(0.5, 1.0))
            label.setPos(x, height + 0.02)
            self.bars.addItem(label)
        line = pg.InfiniteLine(stackcheck.DEAD_GAMMA2, angle=0, pen=theme.mark_pen(theme.BAD_COLOUR))
        self.bars.addItem(line)
        self.bars.setYRange(0.0, 1.12 if marks else 1.0, padding=0.02)  # room for a flag over a bar near 1

    def _fill_preview(self, res) -> None:
        field = channels.kind(res.roles[0]) if res.roles else None
        label = f"stack ({res.stack})" if res.engine == "band" else f"stack (time, {res.weighting})"
        for plot, (title, (b_role, e_role)) in zip(self.panels, PANELS):
            plot.clear()
            role = b_role if field == "magnetic" else e_role
            plot.setTitle(f"{title}: {channels.label(role)}", color=theme.TEXT)
            prev = res.preview.get(role)
            if prev is None or not prev["periods"].size:
                continue
            order = np.argsort(1.0 / prev["periods"])
            freqs = (1.0 / prev["periods"])[order]
            for i in range(prev["members"].shape[0]):
                self._curve(plot, freqs, prev["members"][i][order], pg.mkPen(theme.REMOTE_COLOUR, width=1),
                            "members" if i == 0 else None)
            self._curve(plot, freqs, prev["stack"][order], theme.pen(role, 2.5), label)

    @staticmethod
    def _curve(plot, x, y, pen, name) -> None:
        ok = np.isfinite(y) & (y > 0)
        if ok.any():
            plot.plot(x[ok], y[ok], pen=pen, name=name)

    def _fill_weights(self, res) -> None:
        self.weights.clear()
        if not res.weights:
            self.weights.hide()
            return
        t0 = res.span[0].timestamp()
        chunk = virtual.WEIGHT_CHUNK_S  # the coherence stack's own chunk
        n = len(res.members)
        plot = self.weights.getPlotItem()
        plot.legend.setColumnCount(min(n, LEGEND_MAX_COLUMNS))  # one legend row per channel while the members fit
        largest = 0.0
        for k, (role, w) in enumerate(res.weights.items()):
            largest = max(largest, float(np.nanmax(w)) if np.isfinite(w).any() else 0.0)
            x = t0 + np.arange(w.shape[1]) * chunk
            for i, site in enumerate(res.members):
                # the field's colour (magnetics blue, electrics red); members by opacity, channels by dash
                colour = QColor(theme.colour(role))
                colour.setAlpha(255 - (165 * i) // max(n - 1, 1))
                pen = pg.mkPen(colour, width=1.5, style=Qt.SolidLine if k == 0 else Qt.DashLine)
                self.weights.plot(x, w[i], pen=pen, name=f"{site} {channels.label(role)}")
        self.weights.show()
        self._raise_weights_top(largest)

    def _raise_weights_top(self, largest: float) -> None:
        """Set the weight axis from 0 to a top that leaves the legend's rows above the largest weight.

        Args:
            largest (float): The largest weight drawn.
        """
        plot = self.weights.getPlotItem()
        legend_px = plot.legend.boundingRect().height() + LEGEND_OFFSET[1] + LEGEND_GAP
        plot_px = plot.vb.height()
        share = legend_px / plot_px if plot_px > legend_px else 0.4  # before the layout has a height
        top = max(largest, 1e-3) / (1.0 - share)
        self.weights.setYRange(0.0, top, padding=0.0)
