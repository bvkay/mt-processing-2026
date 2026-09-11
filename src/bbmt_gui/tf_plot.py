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
The dark faces, text, ticks and spines are the rcParams `bbmt_gui.theme.apply`
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

Nothing is produced here: this module only reads EDIs in order to draw them.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path

import matplotlib.pyplot as plt
from mtpy import MT
from mtpy.imaging import PlotMTResponse, PlotMultipleResponses

from bbmt_gui import theme

# the three "Plot" radio buttons, in order
CHOICES = ("rho", "pt", "tipper")
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


def draw(figure, items, choice: str = "rho", title: str = "", hint: str = ""):
    """Draw `items` = [(label, path), ...] on `figure`; return (drawn, problems).

    `choice` is one of `CHOICES`: "rho" is apparent resistivity over phase,
    "pt" adds mtpy's row of phase tensor ellipses (one row per station) and
    "tipper" adds the induction-vector panel. With nothing drawable the
    figure is left empty with `hint` written across it.
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
