# -*- coding: utf-8 -*-
"""
Transfer function plots for the View EDIs tab

`draw(figure, items, choice)` takes a list of (label, path) rows and draws
them with mtpy-v2's plotters: log-log apparent resistivity over phase with
mtpy's error bars, xy and yx (`plot_num=1`). One station is drawn with
`PlotMTResponse`, several with `PlotMultipleResponses(plot_style="compare")`,
which overlays them on one pair of panels (xy left, yx right). EDIs are read
for display only.

The module handles four aspects of mtpy's behaviour.

mtpy creates its own figure through pyplot (`plt.figure(...)` inside
`plot()`), and with `show_plot=False` nothing exists until `.plot()` is
called. For the duration of the call, `_mtpy_draws_on` points
`plt.figure`, `plt.fignum_exists`, `plt.close` and `plt.clf` at the caller's
Figure, so pyplot's registry is left without a stray figure or window. mtpy
also sets a few `plt.rcParams` (font size, subplot margins) as it plots; the
View EDIs canvas is the GUI's only matplotlib user. The dark faces, text,
ticks and spines come from the rcParams `mtproc_gui.theme.apply` sets before
the tab's Figure is made. mtpy 2.1.4 sets none of them, so the figure and
every axes (rho, phase and phase tensor) stay on the theme's grey without
recolouring.

mtpy draws a tipper whenever the file holds one. The aurora EDIs of a survey
with no hz sensor carry a tipper estimated from a dead channel, so the
tipper is drawn only when `choice` is "tipper", and the tab offers that
choice only when the survey declares an hz channel. The phase tensor row is
likewise opt-in ("pt").

mtpy takes the legend text from `mt.station`, which mt_metadata validates
against `^[a-zA-Z0-9_-]*$`, so a file name cannot be used directly. The
station is set to a sanitised form and the legend texts are replaced with
the tab's labels afterwards.

mtpy folds the yx phase into 0-90. `plot_phase`
(`mtpy.imaging.mtplot_tools.plotters`) draws `phase_xy` as is and
`phase_yx + 180` for the yx curve (`yx=True`), then
`set_phase_limits(mode="od")` clamps the axis to 0-90. In mtpy 2.1.4 no
`phase_limits` kwarg or attribute reaches this code, and `PlotMTResponse`
and `PlotMultipleResponses` offer no unfolded mode. `choice` selects
rho, phase tensor or tipper; `phase_range` (`PHASE_CHOICES`) is a separate
post-processing step in `_apply_phase_range`. The default keeps mtpy's fold;
the unfolded choice shifts every yx curve back by -180, so a physical yx
sits near -135 and a mode 180 deg out of quadrant shows as such.

A MANTLE product carries typed verdicts (`mtproc_gui.mantle_products`).
`draw(..., verdicts=(label, ranges))` shortens each resistivity axes from
the bottom and puts a strip there, one row per verdict word coloured by
`mantle_products.colour_of`, spanning the periods the word's verdicts cover
on the same period axis, with the words as its row labels and a legend. The
strip axes carry the label `VERDICT_STRIP`.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.ticker import MultipleLocator
from mtpy import MT
from mtpy.imaging import PlotMTResponse, PlotMultipleResponses

from mtproc_gui import mantle_products, theme

VERDICT_STRIP = "mantle verdicts"  # the label of every verdict-strip axes on the figure
STRIP_ROW = 0.028  # figure fraction per verdict word
STRIP_GAP = 0.012  # figure fraction between the strip and the resistivity axes above it

# the three "Plot" radio buttons, in order
CHOICES = ("rho", "pt", "tipper")
# the two "Phase" radio buttons, in order; PHASE_FOLDED is what mtpy draws today
PHASE_FOLDED = "0-90"
PHASE_UNFOLDED = "-180-180"
PHASE_CHOICES = (PHASE_FOLDED, PHASE_UNFOLDED)
_PHASE_RANGE_LABEL = {
    PHASE_FOLDED: "0 to 90 deg (yx + 180)",
    PHASE_UNFOLDED: "-180 to 180 deg (yx unfolded)",
}
_NOT_A_STATION = re.compile(r"[^A-Za-z0-9_-]")

# one parsed MT per file: an EDI parse through mt_metadata is ~0.1 s, and the
# quick view redraws on every arrow key
_MT_CACHE: dict[str, MT] = {}


def load_mt(path: Path | str) -> MT:
    """Return the `mtpy.MT` for `path`, parsed once and cached (see `clear_cache`)."""
    key = str(Path(path).resolve())
    if key not in _MT_CACHE:
        mt = MT(fn=key)
        mt.read()
        _MT_CACHE[key] = mt
    return _MT_CACHE[key]


def clear_cache() -> None:
    """Forget every parsed EDI, e.g. after a job has rewritten `<workspace>/tf`."""
    _MT_CACHE.clear()


@contextmanager
def _mtpy_draws_on(figure):
    """Context manager that makes mtpy's `plt.figure(...)` return `figure` instead of a new one."""
    saved = (plt.figure, plt.fignum_exists, plt.close, plt.clf)
    plt.figure = lambda *a, **k: figure
    plt.fignum_exists = lambda *a, **k: False
    plt.close = lambda *a, **k: None
    plt.clf = lambda *a, **k: figure.clear()
    try:
        yield
    finally:
        plt.figure, plt.fignum_exists, plt.close, plt.clf = saved


def _station(label: str) -> str:
    """Return `label` sanitised to a valid mt_metadata station id."""
    return _NOT_A_STATION.sub("_", label) or "TF"


def _relabel(plotter, labels: list[str]) -> None:
    """Replace the legend texts of the two resistivity axes with the tab's labels.

    `PlotMultipleResponses` writes one legend entry per station on `axr` and
    `axr2` in drawing order, so the texts match `labels` one for one.
    """
    for axes in (getattr(plotter, "axr", None), getattr(plotter, "axr2", None)):
        legend = None if axes is None else axes.get_legend()
        if legend is None:
            continue
        for text, label in zip(legend.get_texts(), labels):
            text.set_text(label)


def _shift_container(container, delta: float) -> None:
    """Shift one mtpy error-bar container's y data by `delta` degrees, in place.

    `container.lines` is `(data_line, caplines, barlinecols)`
    (`matplotlib.container.ErrorbarContainer`): the marker/line, its cap
    `Line2D`s and the `LineCollection`s drawing the error bars. All three are
    shifted so the bars stay on the line.
    """
    data_line, caplines, barlinecols = container.lines
    if data_line is not None:
        data_line.set_ydata(data_line.get_ydata() + delta)
    for cap in caplines:
        cap.set_ydata(cap.get_ydata() + delta)
    for collection in barlinecols:
        collection.set_segments([seg + (0.0, delta) for seg in collection.get_segments()])


def _apply_phase_range(plotter, phase_range: str) -> None:
    """Fold or unfold the yx phase curves `plotter` has drawn, and set the phase axis.

    `plotter.axp` is the phase axes mtpy always creates. `plotter.axp2`
    exists only for the `PlotMultipleResponses(plot_style="compare")`
    overlay, where xy and yx are drawn on separate axes (`axp` xy only,
    `axp2` yx only; `_plot_compare` in `plot_mt_responses.py`).
    `PlotMTResponse` (one EDI, `plot_num=1`) draws both on `axp`, xy first
    then yx (`_plot_phase`'s `comps = ["xy", "yx"]`), so its containers are
    `axp.containers[0]` and `[1]`. The yx curves are therefore identified
    from the plot structure rather than the data.

    Args:
        plotter: The mtpy plotter after `.plot()`.
        phase_range (str): `PHASE_FOLDED` or `PHASE_UNFOLDED`.
    """
    axp = getattr(plotter, "axp", None)
    axp2 = getattr(plotter, "axp2", None)
    if axp is None:
        return
    if phase_range == PHASE_UNFOLDED:
        if axp2 is not None:  # compare overlay: axp2 holds only yx curves
            for container in axp2.containers:
                _shift_container(container, -180.0)
        elif len(axp.containers) >= 2:  # one axes: containers are [xy, yx]
            _shift_container(axp.containers[1], -180.0)
    # the axis is locked to the chosen range regardless of the data; mtpy's
    # "od" limits widen past 0-90 when a value falls outside the quadrant,
    # which the unfolded choice is meant to show
    lo, hi, step = (-180, 180, 45) if phase_range == PHASE_UNFOLDED else (0, 90, 15)
    label = _PHASE_RANGE_LABEL[phase_range]
    for axes in (axp, axp2):
        if axes is not None:
            axes.set_ylim(lo, hi)
            axes.yaxis.set_major_locator(MultipleLocator(step))
            axes.set_ylabel(f"Phase (deg)\n{label}")


def _apply_rho_limits(plotter, rho_limits: tuple[float | None, float | None]) -> str | None:
    """Set the y limits of the resistivity axes `plotter` has drawn.

    `plotter.axr` is the resistivity axes mtpy always creates. `plotter.axr2`
    exists only for the `PlotMultipleResponses(plot_style="compare")`
    overlay, where xy and yx are drawn on separate resistivity axes (`axr`
    xy, `axr2` yx). In mtpy 2.1.4's `plot_mt_responses.py`, `_plot_compare`
    builds both through `_setup_subplots(gs_master, plot_num=2)` whatever the
    caller's `plot_num`, and near lines 688-691 applies its `res_limits` to
    `axr` and, when present, `axr2`. That kwarg is not used here because a
    blank side should keep mtpy's automatic value, which exists only after
    `.plot()` has run. `PlotMTResponse` (one EDI) creates only `axr`.

    The axes are log scale. A None side keeps the limit mtpy drew
    (`axes.get_ylim()` is read first and only the given side replaced). A
    non-positive limit, or a min at or above the max, leaves the axes
    unchanged.

    Args:
        plotter: The mtpy plotter after `.plot()`.
        rho_limits (tuple[float | None, float | None]): (min, max) in Ohm m.

    Returns:
        str | None: A one-line problem for `draw` to report, or None.
    """
    axr = getattr(plotter, "axr", None)
    if axr is None:
        return None
    lo, hi = rho_limits
    if lo is None and hi is None:
        return None
    if (lo is not None and lo <= 0) or (hi is not None and hi <= 0) or (
        lo is not None and hi is not None and lo >= hi
    ):
        return "rho limits ignored: min must be below max and both above 0"
    for axes in (axr, getattr(plotter, "axr2", None)):
        if axes is None:
            continue
        cur_lo, cur_hi = axes.get_ylim()
        axes.set_ylim(lo if lo is not None else cur_lo, hi if hi is not None else cur_hi)
    return None


def _draw_verdict_strip(plotter, figure, label: str, ranges: dict) -> list:
    """Put a verdict strip under each resistivity axes `plotter` has drawn.

    Each resistivity axes (`axr`, and `axr2` on the compare overlay) gives up
    the strip's height at its bottom; the strip shares its period axis. One
    row per word, top to bottom in `ranges`' order, holds a bar per period
    range in the word's colour; the words are the row labels and a legend
    names them again, titled with `label` on the first strip.

    Args:
        plotter: The mtpy plotter after `.plot()`.
        figure: The figure drawn on.
        label (str): The product the verdicts belong to.
        ranges (dict): `mantle_products.word_ranges` of its report.

    Returns:
        list: The strip axes made, in the order of the resistivity axes.
    """
    words = list(ranges)
    if not words:
        return []
    height = STRIP_ROW * len(words)
    strips = []
    for k, axes in enumerate((getattr(plotter, "axr", None), getattr(plotter, "axr2", None))):
        if axes is None:
            continue
        box = axes.get_position()
        axes.set_position([box.x0, box.y0 + height + STRIP_GAP, box.width, box.height - height - STRIP_GAP])
        strip = figure.add_axes([box.x0, box.y0, box.width, height], sharex=axes, label=VERDICT_STRIP)
        for row, word in enumerate(words):
            y0 = 1.0 - (row + 1) / len(words)
            spans = [(lo, hi - lo) for lo, hi in ranges[word]]
            strip.broken_barh(spans, (y0 + 0.08 / len(words), 0.84 / len(words)),
                              color=mantle_products.colour_of(word), alpha=0.9, linewidth=0)
        strip.set_ylim(0.0, 1.0)
        strip.set_yticks([1.0 - (row + 0.5) / len(words) for row in range(len(words))])
        strip.set_yticklabels(words, fontsize=6)
        strip.tick_params(axis="x", labelbottom=False, length=2)
        strip.tick_params(axis="y", length=0)
        strip.grid(True, axis="x", alpha=0.3)
        handles = [Patch(color=mantle_products.colour_of(w), label=w) for w in words]
        strip.legend(handles=handles, loc="upper right", ncol=len(words), fontsize=6, frameon=False,
                     handlelength=1.0, borderaxespad=0.1, title=f"MANTLE verdicts: {label}" if k == 0 else None,
                     title_fontsize=6)
        strips.append(strip)
    return strips


def draw(figure, items, choice: str = "rho", title: str = "", hint: str = "",
         phase_range: str = PHASE_FOLDED,
         rho_limits: tuple[float | None, float | None] = (None, None),
         verdicts: tuple[str, dict] | None = None):
    """Draw transfer functions on `figure`.

    With nothing drawable the figure is left empty with `hint` written
    across it.

    Args:
        figure: The matplotlib Figure to draw on; cleared first.
        items: (label, EDI path) pairs.
        choice (str): One of `CHOICES`. "rho" is apparent resistivity over
            phase, "pt" adds mtpy's row of phase tensor ellipses (one row per
            station) and "tipper" adds the induction-vector panel.
        title (str): Figure title; defaults to the drawn labels joined by " + ".
        hint (str): Text shown when nothing is drawn.
        phase_range (str): One of `PHASE_CHOICES`. `PHASE_FOLDED` keeps
            mtpy's yx + 180 fold in 0-90; `PHASE_UNFOLDED` shifts every yx
            curve back by -180 onto a -180 to 180 axis (`_apply_phase_range`).
        rho_limits (tuple[float | None, float | None]): (min, max) in Ohm m;
            None on a side keeps mtpy's automatic value (`_apply_rho_limits`).
            An invalid pair is not applied and is reported in `problems`.
        verdicts (tuple[str, dict], optional): ``(label, ranges)`` of a
            MANTLE product among `items` (`mantle_products.word_ranges`),
            drawn as a strip under each resistivity axes
            (`_draw_verdict_strip`).

    Returns:
        tuple[list[str], list[str]]: The labels drawn and the problems met.
    """
    figure.clear()
    drawn: list[str] = []
    problems: list[str] = []
    loaded: list[tuple[str, MT]] = []
    for label, path in items:
        path = Path(path)
        if not path.exists():
            problems.append(f"{label}: not on disk")
            continue
        try:
            loaded.append((label, load_mt(path)))
        except Exception as exc:  # a truncated or foreign EDI
            problems.append(f"{label}: {exc}")
            continue

    if loaded:
        want_pt = choice == "pt"
        want_tipper = "yri" if choice == "tipper" else "n"
        try:
            with _mtpy_draws_on(figure):
                if len(loaded) == 1:
                    label, mt = loaded[0]
                    plotter = PlotMTResponse(
                        z_object=mt.Z,
                        t_object=mt.Tipper if choice == "tipper" else None,
                        pt_obj=mt.pt if want_pt else None,
                        station=label,
                        plot_num=1,
                        plot_tipper=want_tipper,
                        plot_pt=want_pt,
                        show_plot=False,
                    )
                    plotter.plot()
                else:
                    data = {}
                    for label, mt in loaded:
                        mt.station = _station(label)
                        data[label] = mt
                    plotter = PlotMultipleResponses(
                        data,
                        plot_style="compare",
                        plot_num=1,
                        plot_tipper=want_tipper,
                        plot_pt=want_pt,
                        include_survey=False,
                        show_plot=False,
                    )
                    plotter.plot()
                    _relabel(plotter, [label for label, _mt in loaded])
                _apply_phase_range(plotter, phase_range)
                rho_problem = _apply_rho_limits(plotter, rho_limits)
                if rho_problem:
                    problems.append(rho_problem)
                if verdicts is not None and verdicts[1]:
                    _draw_verdict_strip(plotter, figure, verdicts[0], verdicts[1])
            drawn = [label for label, _mt in loaded]
        except Exception as exc:  # mtpy refused the combination
            figure.clear()
            problems.append(f"mtpy could not draw these: {exc}")

    if drawn:
        # above mtpy's own top margin, clear of the corner tick labels
        figure.suptitle(title or " + ".join(drawn), fontsize=10, y=0.995, va="top")
    elif hint:
        figure.text(0.5, 0.5, hint, ha="center", va="center", fontsize=11, color=theme.FOREGROUND)
    return drawn, problems
