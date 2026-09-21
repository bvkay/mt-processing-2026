"""mtpy-v2 glue for the View EDIs tab: transfer functions on one Figure.

`draw(figure, items, choice)` takes the rows the tab wants -- a list of
(label, path) -- and draws them with mtpy-v2's own plotters, so the picture is
the one MT people expect: log-log apparent resistivity over phase with mtpy's
error bars, xy and yx (`plot_num=1`). One station goes through
`PlotMTResponse`, several through `PlotMultipleResponses(plot_style="compare")`,
which overlays them all on one pair of panels (xy left, yx right).

Three mtpy facts shape this module.

*mtpy makes its own figure through pyplot* -- `plt.figure(...)` inside
`plot()` -- and with `show_plot=False` nothing exists until `.plot()` is
called. A GUI needs the picture on the canvas it already has, so for the
length of the call `plt.figure`, `plt.fignum_exists`, `plt.close` and
`plt.clf` are pointed at the caller's Figure (`_mtpy_draws_on`). Nothing is
left in pyplot's registry afterwards: no stray figure, no second window.
mtpy also writes a few `plt.rcParams` (font size, subplot margins) as it
plots; nothing else in this GUI draws with matplotlib, so that is harmless.
The dark faces, text, ticks and spines are the rcParams `mtproc_gui.theme.apply`
set before the tab's Figure was made; mtpy sets none of them (checked on
mtpy 2.1.4: figure and every axes stay on the theme's grey, rho, phase and
phase tensor alike), so nothing is re-coloured here after a draw.

*A tipper is drawn whenever one is in the file.* The aurora EDIs of a survey
with no hz sensor carry a tipper estimated from a dead channel, so it is
nonsense: `choice` must ask for it ("tipper"), and the tab only offers that
when the survey declares an hz channel. The phase tensor row is the same
kind of opt-in ("pt").

*mtpy takes the legend text from `mt.station`*, which mt_metadata validates
against `^[a-zA-Z0-9_-]*$` -- a file name cannot go in directly. The station
is set to a sanitised form and the legend texts are rewritten with the tab's
real labels afterwards.

*mtpy always folds the yx phase into 0-90.* `plot_phase`
(`mtpy.imaging.mtplot_tools.plotters`) draws `phase_xy` as is and
`phase_yx + 180` whenever it is asked for the yx curve (`yx=True`), then
`set_phase_limits(mode="od")` clamps the axis to 0-90 (checked on mtpy
2.1.4's source: no `phase_limits` kwarg or attribute reaches this far, and
`PlotMTResponse`/`PlotMultipleResponses` offer no unfolded mode). `choice`
picks xy/phase-tensor/tipper; `phase_range` (`PHASE_CHOICES`) is a second,
independent post-processing step, below `_apply_phase_range`: the default
leaves mtpy's fold as it is, the other undoes it by shifting every yx curve
mtpy just drew back by -180 -- a physical yx then sits near -135 and a mode
180 deg out of quadrant is visible as such, rather than hidden inside 0-90.

Nothing is produced here: this module only reads EDIs in order to draw them.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
from mtpy import MT
from mtpy.imaging import PlotMTResponse, PlotMultipleResponses

from mtproc_gui import theme

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
    """`mtpy.MT` for `path`, read once per session (see `clear_cache`)."""
    key = str(Path(path).resolve())
    if key not in _MT_CACHE:
        mt = MT(fn=key)
        mt.read()
        _MT_CACHE[key] = mt
    return _MT_CACHE[key]


def clear_cache() -> None:
    """Forget every parsed EDI -- a job has rewritten `<workspace>/tf`."""
    _MT_CACHE.clear()


@contextmanager
def _mtpy_draws_on(figure):
    """Make mtpy's `plt.figure(...)` hand back `figure` instead of a new one."""
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
    """`label` as mt_metadata will accept it for a station id."""
    return _NOT_A_STATION.sub("_", label) or "TF"


def _relabel(plotter, labels: list[str]) -> None:
    """Put the tab's labels back in the two resistivity legends.

    `PlotMultipleResponses` writes one legend entry per station on `axr` and
    `axr2`, in the order the stations were drawn, so the texts line up with
    `labels` one for one.
    """
    for axes in (getattr(plotter, "axr", None), getattr(plotter, "axr2", None)):
        legend = None if axes is None else axes.get_legend()
        if legend is None:
            continue
        for text, label in zip(legend.get_texts(), labels):
            text.set_text(label)


def _shift_container(container, delta: float) -> None:
    """Move one mtpy error-bar container's y data by `delta` degrees, in place.

    `container.lines` is `(data_line, caplines, barlinecols)`
    (`matplotlib.container.ErrorbarContainer`): the marker/line itself, its
    cap `Line2D`s, and the `LineCollection`(s) drawing the error bars. All
    three carry y values that must move together or the bars would no
    longer sit on the shifted line.
    """
    data_line, caplines, barlinecols = container.lines
    if data_line is not None:
        data_line.set_ydata(data_line.get_ydata() + delta)
    for cap in caplines:
        cap.set_ydata(cap.get_ydata() + delta)
    for collection in barlinecols:
        collection.set_segments([seg + (0.0, delta) for seg in collection.get_segments()])


def _apply_phase_range(plotter, phase_range: str) -> None:
    """Fold or unfold the yx phase curve(s) `plotter` just drew, on its own axes.

    `plotter.axp` is the phase axes mtpy always makes; `plotter.axp2` exists
    only for `PlotMultipleResponses(plot_style="compare")`'s overlay, where
    xy and yx are drawn on separate axes (`axp` xy-only, `axp2` yx-only,
    `plot_mt_responses.py`'s `_plot_compare`). `PlotMTResponse` (one EDI on
    its own, `plot_num=1`) draws both on the one `axp`, xy first then yx in a
    fixed order (`_plot_phase`'s `comps = ["xy", "yx"]`), so its two
    containers are `axp.containers[0]` and `[1]`. Either way the yx curve(s)
    are found without guessing from the data.
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
    # the axis is locked to the chosen range whatever the data do: mtpy's own
    # "od" limits widen past 0-90 when a value falls outside the quadrant, and
    # seeing that is what the unfolded choice is for
    lo, hi, step = (-180, 180, 45) if phase_range == PHASE_UNFOLDED else (0, 90, 15)
    label = _PHASE_RANGE_LABEL[phase_range]
    for axes in (axp, axp2):
        if axes is not None:
            axes.set_ylim(lo, hi)
            axes.yaxis.set_major_locator(MultipleLocator(step))
            axes.set_ylabel(f"Phase (deg)\n{label}")


def _apply_rho_limits(plotter, rho_limits: tuple[float | None, float | None]) -> str | None:
    """Clamp the resistivity axes' y limits `plotter` just drew, on its own axes.

    `plotter.axr` is the resistivity axes mtpy always makes; `plotter.axr2`
    exists only for `PlotMultipleResponses(plot_style="compare")`'s overlay,
    where xy and yx are drawn on separate resistivity axes (`axr` xy, `axr2`
    yx -- checked on mtpy 2.1.4's `plot_mt_responses.py`: `_plot_compare`
    builds both through `_setup_subplots(gs_master, plot_num=2)` regardless
    of the caller's own `plot_num`, and at the end, ~line 688-691, applies
    its own `res_limits` the same way this does -- `axr.set_ylim(...)` then,
    when `axr2 is not None`, `axr2.set_ylim(...)` too -- which is exactly why
    that kwarg cannot be used here: with one side blank we want mtpy's own
    automatic value on that side, and that value exists only after `.plot()`
    has already run). `PlotMTResponse` (one EDI on its own) makes only `axr`.

    The axes are log scale. A None side of `rho_limits` keeps whatever mtpy
    drew there (`axes.get_ylim()`, read before either side is touched, then
    only the given side replaced). A non-positive limit or a min at or above
    the max is refused outright -- nothing is changed -- and a one-line
    problem string is returned for `draw` to report; otherwise None.
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


def draw(figure, items, choice: str = "rho", title: str = "", hint: str = "",
         phase_range: str = PHASE_FOLDED,
         rho_limits: tuple[float | None, float | None] = (None, None)):
    """Draw `items` = [(label, path), ...] on `figure`; return (drawn, problems).

    `choice` is one of `CHOICES`: "rho" is apparent resistivity over phase,
    "pt" adds mtpy's row of phase tensor ellipses (one row per station) and
    "tipper" adds the induction-vector panel. `phase_range` is one of
    `PHASE_CHOICES`: `PHASE_FOLDED` (default) leaves mtpy's own yx + 180
    fold in 0-90, `PHASE_UNFOLDED` shifts every yx curve back by -180 onto
    a -180 to 180 axis (`_apply_phase_range`). `rho_limits` is (min, max) in
    Ohm m, either side `None` for mtpy's own automatic value on that side
    (`_apply_rho_limits`); an invalid pair is left unapplied and noted in
    `problems` instead. With nothing drawable the figure is left empty with
    `hint` written across it.
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
