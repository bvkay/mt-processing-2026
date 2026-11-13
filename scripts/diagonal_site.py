# -*- coding: utf-8 -*-
"""
Write the diagonal electric field of a site with a shared centre electrode as a derived site

An Earth Data PR6-24 (EDL) site measures its lines off one centre
electrode C: the logger's ex input holds V(N) - V(C) and its ey input
V(E) - V(C). A noisy or disconnected centre puts one voltage on both, and
the difference of the two lines, V(N) - V(E), is a dipole free of it, from
the E electrode to the N electrode
(`scripts/shared_centre_test.py` says where the model holds and with which
sign). This script writes it as the derived site ``<site>D``, whose archive
holds one electric line and the site's magnetics, for process_rr.py to
estimate the one impedance row it carries (and the tipper).

The archive, ``<workspace>/mth5/<site>D.h5``, holds station ``<site>D`` in
the source's MTH5 survey, one run per source run with the same id. Its ex
is the source's ex minus s times its ey, sample for sample, in the
logger's own units (the archive's microvolts, before every filter stage):
ex := ex - s ey, exact in float64 for the logger's integer words. hx, hy and
hz are copied with their chains (the fluxgate turn `rot_h` is already in
the source). The source is the site's processing archive
(`mt_workbench.ingest.processing_archive`).

The subtraction is meaningful only because the two electric chains are the
same up to the dipole stage: `check_chains` refuses a run whose ex and ey
chains differ in any stage but the dipole (type, name, gain and units,
stage for stage), whose dipole stages are not one coefficient filter each
at the same place, or whose samples differ in rate, start or count.

The geometry. In an archive written by `mt_workbench.ingest` a line's
samples are B g E.u(a), where B is the product of its other stages (the x10
terminal box), g its dipole stage's signed gain (mt-io's sign: -L for a
line laid along its channel's nominal azimuth, +L for one laid the other
way, at 180 or 270 deg), a its channel's measurement azimuth (0 for ex, 90
for ey) and u(a) the unit vector at azimuth a (north, east). So
ex - s ey = B w.E with w = g_x u(a_x) - s g_y u(a_y), and the derived line is
written as one laid along its own azimuth: dipole stage gain -L_d,
measurement azimuth theta_d, with L_d = |w| = sqrt(Lx^2 + Ly^2) and u(theta_d) =
-w / |w|. Sign convention: theta_d, in degrees clockwise
from magnetic north in [0, 360), is the azimuth of the vector
Lx u(az_x) - s Ly u(az_y), where az_x and az_y are the lines' declared
layout azimuths (ex 0 or 180, ey 90 or 270), so that the calibrated derived
ex is the electric field along theta_d. For the standard layout (0/90)
this is theta_d = atan2(-s Ly, Lx): 315 deg for equal arms with s = +1,
the dipole from the E electrode to the N electrode; s = -1 gives
atan2(+Ly, Lx), 45 deg; a reversed ey (0/270) with s = +1 gives 45 deg.
For s = +1 the vector runs between the two outer electrodes; for s = -1 its
tail is the ey electrode reflected through the centre (the dipole the
combination is equivalent to). The derived ex's metadata states the
geometry: `dipole_length` L_d, `measurement_azimuth` theta_d, and the
electrode coordinates relative to the centre (north x, east y, m) of
the negative end s Ly u(az_y) and the positive end Lx u(az_x), which the EDI
writes as EMEAS X, Y, X2, Y2 with AZM theta_d.

Each run comment ("derived_by: diagonal_site <version>, from <source>
<run>, ex = ex - (s) ey in the logger's microvolts before the dipole
stages, s <+1|-1>, L_d <m> m, theta_d <deg> deg from magnetic north")
names the source archive and run, s, L_d and theta_d, then the source
archive's identity as read (``source: ...``, `mt_workbench.ingest.source_note`)
and the source run's own comment, as scripts/decimate_site.py writes its
own; an existing archive is kept while current
(`decimate_site.derived_stale`: the source archive unchanged since) and
cut with the same s, and rebuilt otherwise or with --force. After the
write every run is read back: the derived ex must equal ex - s ey of the
source exactly, and hx, hy, hz the source's.

A site whose pair the ingest turned (`mt_workbench.ingest._rot_e`;
the station's provenance line "rot_e: ex <a_x> deg, ey <a_y> deg as
laid", read by `archive_rot_e`) holds E_N and E_E in its ex and ey, linear
combinations of the two recorded lines, and the centre's voltage cancels
only between the lines as recorded. There the turn is
undone first, exactly (`recorded_lines`): with b_x, b_y the directions the
recorded lines measure along (`_e_direction` of the as-laid azimuths), M =
[[cos b_x, sin b_x], [cos b_y, sin b_y]] (the matrix `_rot_e_matrix`
inverts) and k = g_y / g_x the ratio of the two dipole stages' signed gains
(the rest of the chains being common, `check_chains`), the ingest wrote
X = i00 x + (i01 / k) y and Y = k i10 x + i11 y with i = inv(M), so
x = M00 X + (M01 / k) Y and y = k M10 X + M11 Y. The logger's words are
integers, so the recovered lines must be integers to float rounding: they
are rounded to them, and a run whose recovered lines are more than
`UNTURN_TOLERANCE` words from an integer anywhere is refused (a wrong
azimuth or gain leaves fractions; checked against the raw files of NF41_2
and SA009 to 5e-10 words).
The geometry is then the recorded lines': the signed gains with the
measuring directions b_x, b_y in place of the archive's 0 and 90
(`archive_geometry`), which must equal `diagonal_geometry` of the as-laid
azimuths. The run comment says so (", rot_e undone first (...)"). Only an
EDL rot_e site is undone (the shared centre is the EDL's); a rot_e site of
another instrument is refused.

s: --sign, else the `s_obs` of the site's row in
`<workspace>/qc/shared_centre/centre_test.csv` when its verdict is "holds",
else +1, the prediction (the centre on the minus terminal of both inputs).

survey.yaml gains the entry ``<site>D: {derived_from, channels: [ex, hx,
hy, hz], sample_rate, dipole_length_ex: L_d, azimuth_ex: theta_d,
latitude, longitude, elevation, declination, declination_model,
declination_epoch, start, end, notes}`` (hz left out when the source has
none), in place (`add_entry_in_place`): the entry's text is appended at the
end of the sites block, or replaces the entry's own lines when it is there
already, and every other line is kept unchanged; the new text is parsed
and compared with the old (top level equal, every other site equal, the one
entry the only change), its comment count must equal the old one, and
`Survey` must accept every site of it. A copy of the file goes beside it
first (``survey.yaml.before_diagonal_<site>_<stamp>``) and the new text is
written to a temporary file and moved onto survey.yaml (os.replace,
retried while another process holds the file). The rest of the sites
block stays as written (upstream 91). --dry-run prints the chain check, the geometry,
the entry and the parsed diff and writes nothing.

Exit status: 0 done, 2 when the site or the name <site>D does not fit, the
chains differ, or the survey.yaml edit is refused; 3 when the memory wait
runs out.

Usage:
    python scripts/diagonal_site.py <survey.yaml> <site> [--sign +1|-1] [--force] [--dry-run] [--min-free-gb G]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import math
import os
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from decimate_site import (  # noqa: E402
    SOURCE_RUN_COMMENT, _metadata_copy, _run_comment, _run_metadata, derived_stale, wait_for_memory,
)
from mt_workbench import __version__ as WORKBENCH_VERSION  # noqa: E402
from mt_workbench.ingest import (  # noqa: E402
    _all_real_run_comments, _e_direction, archive_rot_e, default_archive_path, processing_archive, source_note,
)
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.timefreq import _real_runs  # noqa: E402

SUFFIX = "D"  # <site>D, the diagonal derived site
DERIVED_BY = "derived_by: diagonal_site "
ISO = "%Y-%m-%dT%H:%M:%SZ"
CENTRE_TABLE = Path("qc") / "shared_centre" / "centre_test.csv"
DIPOLE_UNITS = ("milliVolt per kilometer", "microVolt")
COMMENT = re.compile(r"(^|\s)#")
SIGN_IN_COMMENT = re.compile(r"\bs ([+-]1)\b")
ENTRY_KEYS = ("derived_from", "channels", "sample_rate", "dipole_length_ex", "azimuth_ex", "latitude", "longitude",
              "elevation", "declination", "declination_model", "declination_epoch", "start", "end", "notes")
UNTURN_TOLERANCE = 1e-6  # words: the recovered lines of a rot_e site must be the logger's integers to this
REPLACE_TRIES = 20
REPLACE_WAIT_S = 3.0


def derived_name(site: str) -> str:
    """Return the derived site's name, ``<site>D``."""
    return f"{site}{SUFFIX}"


def iso_utc(t: pd.Timestamp) -> str:
    """Return a UTC instant as ISO text ending in Z, with its fraction of a second only when it has one."""
    t = pd.Timestamp(t)
    t = t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    if t.microsecond == 0 and t.nanosecond == 0:
        return t.strftime(ISO)
    return t.tz_localize(None).isoformat() + "Z"


# ---------------------------------------------------------------- geometry


def unit(azimuth_deg: float) -> np.ndarray:
    """Return the unit vector (north, east) at an azimuth in degrees clockwise from north."""
    a = math.radians(azimuth_deg)
    return np.array([math.cos(a), math.sin(a)])


def diagonal_geometry(length_x: float, az_x: float, length_y: float, az_y: float, s: int) -> dict:
    """Return the diagonal dipole of two lines off one centre from their declared layout.

    Args:
        length_x (float): Ex line length in m.
        az_x (float): Ex layout azimuth in degrees (0 or 180).
        length_y (float): Ey line length in m.
        az_y (float): Ey layout azimuth in degrees (90 or 270).
        s (int): +1 or -1, the sign in ex - s ey.

    Returns:
        dict: ``length`` (L_d, m), ``azimuth`` (theta_d, degrees clockwise
        from north in [0, 360)), ``positive`` and ``negative`` (the ends'
        (north, east) coordinates in m from the centre: Lx u(az_x) and
        s Ly u(az_y)).

    Raises:
        ValueError: If s is not +1 or -1 or a length is not positive.
    """
    if s not in (1, -1):
        raise ValueError(f"s {s!r} is not +1 or -1")
    if not (length_x > 0 and length_y > 0):
        raise ValueError(f"line lengths {length_x!r}, {length_y!r} are not both positive")
    positive = length_x * unit(az_x)
    negative = s * length_y * unit(az_y)
    v = positive - negative
    return dict(length=float(np.hypot(*v)), azimuth=float(math.degrees(math.atan2(v[1], v[0])) % 360.0),
                positive=tuple(float(c) for c in positive), negative=tuple(float(c) for c in negative))


def archive_geometry(gain_x: float, meas_az_x: float, gain_y: float, meas_az_y: float, s: int) -> dict:
    """Return the diagonal dipole from the archive's own dipole stages (signed gains) and channel azimuths.

    The samples of a line are B g E.u(a) (module docstring), so a stage of
    gain g at channel azimuth a is a line of length |g| laid at a when g is
    negative and at a + 180 when it is positive.

    Args:
        gain_x (float): Signed gain of ex's dipole stage.
        meas_az_x (float): ex's measurement azimuth in the archive.
        gain_y (float): Signed gain of ey's dipole stage.
        meas_az_y (float): ey's measurement azimuth in the archive.
        s (int): +1 or -1.

    Returns:
        dict: As `diagonal_geometry`.
    """
    def layout(g, a):
        return abs(g), (a if g < 0 else a + 180.0) % 360.0

    lx, ax = layout(gain_x, meas_az_x)
    ly, ay = layout(gain_y, meas_az_y)
    return diagonal_geometry(lx, ax, ly, ay, s)


def recorded_directions(laid: tuple[float, float]) -> tuple[float, float]:
    """Return the directions (deg) the recorded ex and ey of a rot_e site measure along, from their as-laid azimuths."""
    return _e_direction("ex", laid[0]), _e_direction("ey", laid[1])


def unturn_matrix(bx: float, by: float, k: float) -> np.ndarray:
    """Return the matrix taking a rot_e archive's (ex, ey) samples back to the recorded lines' samples.

    The ingest wrote X = i00 x + (i01 / k) y and Y = k i10 x + i11 y, i the
    inverse of M = [[cos bx, sin bx], [cos by, sin by]] (`_rot_e_matrix`),
    k = g_y / g_x; that is [X; Y] = D i D^-1 [x; y] with D = diag(1, k), so
    [x; y] = D M D^-1 [X; Y] = [[M00, M01 / k], [k M10, M11]] [X; Y].
    """
    a, b = math.radians(bx), math.radians(by)
    return np.array([[math.cos(a), math.sin(a) / k], [k * math.cos(b), math.sin(b)]])


def recorded_lines(x_arch: np.ndarray, y_arch: np.ndarray, laid: tuple[float, float], gain_x: float,
                   gain_y: float) -> tuple[np.ndarray, np.ndarray, float]:
    """Undo the rot_e turn of one run's ex and ey samples: the logger's words of the lines as recorded.

    Args:
        x_arch (np.ndarray): The archive's ex samples (E_N through ex's chain).
        y_arch (np.ndarray): The archive's ey samples (E_E through ey's chain).
        laid (tuple): The as-laid azimuths (a_x, a_y) of `archive_rot_e`.
        gain_x (float): The signed gain of ex's dipole stage.
        gain_y (float): The signed gain of ey's dipole stage.

    Returns:
        tuple: (x, y, worst): the recorded lines rounded to the logger's
        integer words (NaN kept), and the largest distance from an integer
        before the rounding.

    Raises:
        ValueError: If any finite recovered sample is more than
            `UNTURN_TOLERANCE` words from an integer.
    """
    bx, by = recorded_directions(laid)
    u = unturn_matrix(bx, by, gain_y / gain_x)
    xa, ya = np.asarray(x_arch, dtype="float64"), np.asarray(y_arch, dtype="float64")
    x = u[0, 0] * xa + u[0, 1] * ya
    y = u[1, 0] * xa + u[1, 1] * ya
    worst = 0.0
    for z in (x, y):
        fin = np.isfinite(z)
        if fin.any():
            worst = max(worst, float(np.max(np.abs(z[fin] - np.rint(z[fin])))))
    if worst > UNTURN_TOLERANCE:
        raise ValueError(f"undoing rot_e (laid {laid[0]:g}/{laid[1]:g}, measuring along {bx:g}/{by:g}, k "
                         f"{gain_y / gain_x:.6g}) leaves samples {worst:.3g} words from the logger's integers: the "
                         f"as-laid azimuths or the gains are not the ones the ingest turned with")
    return np.rint(x), np.rint(y), worst


# ---------------------------------------------------------------- the chains


def _is_dipole(f) -> bool:
    """Whether a filter is a dipole stage (mt-io's ``uoa_dipole_<c>_<L>m``, ``lemi423_dipole_...``)."""
    return "_dipole_" in str(f.name)


def _stage_record(f) -> dict:
    """Return a filter stage's comparable record: its full metadata less the HDF5 bookkeeping."""
    values = f.to_dict(single=True)
    for key in ("hdf5_reference", "mth5_type", "sequence_number"):
        values.pop(key, None)
    return values


def check_chains(ex_response, ey_response) -> int:
    """Refuse two electric chains that differ in any stage but the dipole.

    Args:
        ex_response (ChannelResponse): ex's chain.
        ey_response (ChannelResponse): ey's chain.

    Returns:
        int: The index of the dipole stage in both chains.

    Raises:
        ValueError: If either chain has no dipole stage or more than one,
            they sit at different places, a dipole stage is not a
            coefficient filter in mV/km to microvolts, the chains differ in
            length, or any other stage differs (named).
    """
    fx, fy = list(ex_response.filters_list), list(ey_response.filters_list)
    names = ([f.name for f in fx], [f.name for f in fy])
    dx = [k for k, f in enumerate(fx) if _is_dipole(f)]
    dy = [k for k, f in enumerate(fy) if _is_dipole(f)]
    if len(dx) != 1 or len(dy) != 1 or dx != dy:
        raise ValueError(f"the chains do not have one dipole stage each at the same place (ex {names[0]}, ey "
                         f"{names[1]})")
    if len(fx) != len(fy):
        raise ValueError(f"the chains differ in length (ex {names[0]}, ey {names[1]})")
    k = dx[0]
    for comp, f in (("ex", fx[k]), ("ey", fy[k])):
        if type(f).__name__ != "CoefficientFilter" or (str(f.units_in), str(f.units_out)) != DIPOLE_UNITS:
            raise ValueError(f"{comp}'s dipole stage {f.name} is not a coefficient filter from {DIPOLE_UNITS[0]} to "
                             f"{DIPOLE_UNITS[1]} ({type(f).__name__}, {f.units_in} -> {f.units_out})")
    for j, (a, b) in enumerate(zip(fx, fy)):
        if j == k:
            continue
        ra, rb = _stage_record(a), _stage_record(b)
        if type(a) is not type(b) or ra != rb:
            diff = sorted(key for key in set(ra) | set(rb) if ra.get(key) != rb.get(key))
            raise ValueError(f"stage {j + 1} differs between ex ({a.name}) and ey ({b.name}): {', '.join(diff) or 'type'}"
                             f"; the samples of two different chains cannot be subtracted")
    return k


# ---------------------------------------------------------------- the archive


def _comment_sign(comment: str) -> int | None:
    """Return the s a derived run comment records, None when it records none."""
    head = (comment or "").split("; ")[0]
    m = SIGN_IN_COMMENT.search(head) if head.startswith(DERIVED_BY) else None
    return int(m.group(1)) if m else None


def archive_sign(path: Path) -> int | None:
    """Return the s every run of an existing derived archive records; None when they disagree or record none."""
    signs = {_comment_sign(c) for c in (_all_real_run_comments(path) or [])}
    return signs.pop() if len(signs) == 1 else None


def _response(ch):
    """Return a channel's response (mt_metadata ChannelResponse), deep-copied."""
    return copy.deepcopy(ch.channel_response)


def derived_ex(ex_ch, ey_ch, s: int, laid: tuple[float, float] | None = None) -> tuple[object, object, dict]:
    """Return the derived ex's metadata, chain and geometry from one run's ex and ey.

    Args:
        ex_ch: The source run's ex channel group.
        ey_ch: Its ey channel group.
        s (int): +1 or -1.
        laid (tuple or None): The as-laid azimuths of a rot_e site (`archive_rot_e`): the geometry is then the
            recorded lines', measuring along `recorded_directions(laid)`, not the archive's 0 and 90.

    Returns:
        tuple: (channel metadata, ChannelResponse, geometry dict of
        `archive_geometry` plus ``dipole_stage`` index and the source
        ``gain_x``/``gain_y``).

    Raises:
        ValueError: From `check_chains`, or when the two channels differ in
            sample rate, start or sample count.
    """
    mx, my = ex_ch.metadata, ey_ch.metadata
    nx, ny = ex_ch.hdf5_dataset.shape[0], ey_ch.hdf5_dataset.shape[0]
    if float(mx.sample_rate) != float(my.sample_rate) or nx != ny or \
            pd.Timestamp(str(mx.time_period.start)) != pd.Timestamp(str(my.time_period.start)):
        raise ValueError(f"ex and ey differ in rate, start or count ({mx.sample_rate} / {my.sample_rate} Hz, "
                         f"{mx.time_period.start} / {my.time_period.start}, {nx} / {ny} samples)")
    rx, ry = _response(ex_ch), _response(ey_ch)
    k = check_chains(rx, ry)
    gx, gy = float(rx.filters_list[k].gain), float(ry.filters_list[k].gain)
    if laid is None:
        geo = archive_geometry(gx, float(mx.measurement_azimuth), gy, float(my.measurement_azimuth), s)
    else:
        bx, by = recorded_directions(laid)
        geo = archive_geometry(gx, bx, gy, by, s)
        want = diagonal_geometry(abs(gx), float(laid[0]), abs(gy), float(laid[1]), s)
        if abs(want["length"] - geo["length"]) > 1e-9 or \
                abs((want["azimuth"] - geo["azimuth"] + 180.0) % 360.0 - 180.0) > 1e-9:
            raise ValueError(f"the dipole stages' signs (ex {gx:+g}, ey {gy:+g}) do not fit the as-laid azimuths "
                             f"{laid[0]:g}/{laid[1]:g} (measuring along {bx:g}/{by:g})")
    geo.update(dipole_stage=k, gain_x=gx, gain_y=gy)
    stage = copy.deepcopy(rx.filters_list[k])
    old_name = stage.name
    stage.name = f"diagonal_dipole_ex_{geo['length']:.3f}m"
    stage.gain = -geo["length"]
    stage.comments = (f"diagonal ex - ({s:+d}) ey of a shared-centre layout: length {geo['length']:.4f} m along "
                      f"{geo['azimuth']:.4f} deg from magnetic north (scripts/diagonal_site.py)")
    filters = list(rx.filters_list)
    filters[k] = stage
    rx.filters_list = filters
    meta = _metadata_copy(mx)
    for applied in meta.filters:
        if applied.name == old_name:
            applied.name = stage.name
    meta.dipole_length = geo["length"]
    meta.measurement_azimuth = geo["azimuth"]
    meta.negative.x, meta.negative.y = geo["negative"]
    meta.positive.x2, meta.positive.y2 = geo["positive"]
    return meta, rx, geo


def source_lines(run_in, laid: tuple[float, float] | None) -> tuple[np.ndarray, np.ndarray, str]:
    """Return one source run's ex and ey as recorded (the turn undone at a rot_e site) and a note for the run comment."""
    ex_ch, ey_ch = run_in.get_channel("ex"), run_in.get_channel("ey")
    x = np.asarray(ex_ch.hdf5_dataset[()], dtype="float64")
    y = np.asarray(ey_ch.hdf5_dataset[()], dtype="float64")
    if laid is None:
        return x, y, ""
    k = check_chains(_response(ex_ch), _response(ey_ch))
    gx = float(ex_ch.channel_response.filters_list[k].gain)
    gy = float(ey_ch.channel_response.filters_list[k].gain)
    x, y, worst = recorded_lines(x, y, laid, gx, gy)
    bx, by = recorded_directions(laid)
    return x, y, (f", rot_e undone first (laid {laid[0]:g}/{laid[1]:g}, measuring along {bx:g}/{by:g}, k "
                  f"{gy / gx:.6g}, the recorded lines within {worst:.1e} words of the logger's integers)")


def write_derived(source: Path, site: str, out_path: Path, s: int, min_free_gb: float = 0.0,
                  laid: tuple[float, float] | None = None) -> list[dict]:
    """Write the diagonal archive of a site and read it back.

    The source is opened read-only; the output is written under a ``.part``
    name and moved onto `out_path` once every run is written and checked.

    Args:
        source (Path): The site's processing archive.
        site (str): Station id in `source`.
        out_path (Path): The derived archive.
        s (int): +1 or -1.
        min_free_gb (float): Memory to wait for before each run is read.
        laid (tuple or None): The as-laid azimuths of a rot_e site (`archive_rot_e`), whose turn is undone
            before the subtraction (`source_lines`); None at a cardinal site.

    Returns:
        list[dict]: Per run: ``id``, ``start``, ``end`` (UTC ISO), ``n``,
        ``channels``, ``rate`` and the geometry (``length``, ``azimuth``,
        ``positive``, ``negative``, ``gain_x``, ``gain_y``).

    Raises:
        ValueError: If a run lacks ex or ey, the chains differ, the runs'
            geometries differ, or the read-back finds a sample off.
        MemoryError: From `wait_for_memory`.
    """
    from mt_timeseries import ChannelTS
    from mth5.mth5 import MTH5

    name = derived_name(site)
    source_record = source_note(source)
    tmp = out_path.with_name(out_path.name + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()
    runs = []
    m_in = MTH5()
    m_in.open_mth5(source, mode="r")
    m_out = MTH5(file_version="0.2.0")
    m_out.open_mth5(tmp, mode="w")
    try:
        survey_id = m_in.surveys_group.groups_list[0]
        station_in = m_in.get_station(site, survey=survey_id)
        m_out.add_survey(survey_id)
        station_out = m_out.add_station(name, survey=survey_id)
        station_out.metadata.update(station_in.metadata)
        station_out.metadata.id = name
        station_out.write_metadata()
        for run_id, _t0, _t1 in _real_runs(station_in):
            run_in = station_in.get_run(run_id)
            comps = list(run_in.groups_list)
            missing = [c for c in ("ex", "ey") if c not in comps]
            if missing:
                raise ValueError(f"{site} {run_id} has no {', '.join(missing)}")
            wait_for_memory(min_free_gb, f"{site} {run_id}")
            ex_ch, ey_ch = run_in.get_channel("ex"), run_in.get_channel("ey")
            meta, response, geo = derived_ex(ex_ch, ey_ch, s, laid)
            if runs and (abs(geo["length"] - runs[0]["length"]) > 1e-9 or abs(geo["azimuth"] - runs[0]["azimuth"]) > 1e-9):
                raise ValueError(f"{site} {run_id}: geometry {geo['length']:.4f} m at {geo['azimuth']:.4f} deg differs "
                                 f"from run {runs[0]['id']}'s")
            run_out = station_out.add_run(run_id)
            xr, yr, unturned = source_lines(run_in, laid)
            x = xr - s * yr
            del xr, yr
            ts = ChannelTS("electric", data=x, channel_metadata=meta)
            ts.channel_response = response
            run_out.from_channel_ts(ts)
            del x
            kept = ["ex"]
            for comp in ("hx", "hy", "hz"):
                if comp not in comps:
                    continue
                ch = run_in.get_channel(comp)
                ts = ChannelTS(ch.metadata.type, data=np.asarray(ch.hdf5_dataset[()], dtype="float64"),
                               channel_metadata=_metadata_copy(ch.metadata))
                ts.channel_response = ch.channel_response
                run_out.from_channel_ts(ts)
                kept.append(comp)
            fs = float(ex_ch.metadata.sample_rate)
            n = int(ex_ch.hdf5_dataset.shape[0])
            start = pd.Timestamp(str(ex_ch.metadata.time_period.start))
            run_out.metadata.update(_run_metadata(run_in.metadata))
            run_out.metadata.id = run_id
            run_out.metadata.comments = (
                f"{DERIVED_BY}{WORKBENCH_VERSION}, from {source.name} {run_id}, ex = ex - ({s:+d}) ey in the logger's "
                f"microvolts before the dipole stages, s {s:+d}, L_d {geo['length']:.4f} m, theta_d "
                f"{geo['azimuth']:.4f} deg from magnetic north{unturned}; {source_record}; "
                f"{SOURCE_RUN_COMMENT}{_run_comment(run_in) or 'none'}")
            run_out.write_metadata()
            run_out.update_metadata()
            end = start + pd.Timedelta(seconds=(n - 1) / fs)
            runs.append(dict(id=run_id, start=iso_utc(start), end=iso_utc(end), n=n, rate=fs,
                             channels=kept, **geo))
            print(f"  run {run_id}: {runs[-1]['start']} .. {runs[-1]['end']} ({n} samples, {', '.join(kept)})",
                  flush=True)
        if not runs:
            raise ValueError(f"{site}: {source.name} holds no run")
        station_out.update_metadata()
        station_out.metadata.run_list = [r["id"] for r in runs]
        station_out.write_metadata()
    except BaseException:
        m_out.close_mth5()
        m_in.close_mth5()
        tmp.unlink(missing_ok=True)
        raise
    m_out.close_mth5()
    m_in.close_mth5()
    try:
        read_back(source, tmp, site, s, laid)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, out_path)
    return runs


def read_back(source: Path, derived: Path, site: str, s: int, laid: tuple[float, float] | None = None) -> None:
    """Check a derived archive against its source: ex == ex - s ey exactly, hx hy hz equal, every run.

    At a rot_e site (`laid` given) ex and ey are the recorded lines, the turn undone (`source_lines`).

    Raises:
        ValueError: Naming the first run and channel that differ.
    """
    from mth5.mth5 import MTH5

    a, b = MTH5(), MTH5()
    a.open_mth5(source, mode="r")
    b.open_mth5(derived, mode="r")
    try:
        sid = a.surveys_group.groups_list[0]
        st_a = a.get_station(site, survey=sid)
        st_b = b.get_station(derived_name(site), survey=sid)
        for run_id, _t0, _t1 in _real_runs(st_a):
            ra, rb = st_a.get_run(run_id), st_b.get_run(run_id)
            xr, yr, _ = source_lines(ra, laid)
            want = xr - s * yr
            got = np.asarray(rb.get_channel("ex").hdf5_dataset[()], "float64")
            if got.shape != want.shape or not np.array_equal(got, want, equal_nan=True):
                raise ValueError(f"{run_id} ex is not ex - ({s:+d}) ey of the source")
            for comp in ("hx", "hy", "hz"):
                if comp in ra.groups_list and not np.array_equal(ra.get_channel(comp).hdf5_dataset[()],
                                                                 rb.get_channel(comp).hdf5_dataset[()]):
                    raise ValueError(f"{run_id} {comp} differs from the source's")
    finally:
        a.close_mth5()
        b.close_mth5()


def archive_runs(path: Path, station: str) -> list[dict]:
    """List an existing derived archive's runs with their span, rate, channels and ex geometry."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(station, survey=m.surveys_group.groups_list[0])
        out = []
        for run_id, start, end in _real_runs(st):
            run = st.get_run(run_id)
            md = run.get_channel("ex").metadata
            out.append(dict(id=run_id, start=iso_utc(start), end=iso_utc(end),
                            rate=float(run.metadata.sample_rate), channels=list(run.groups_list),
                            length=float(md.dipole_length), azimuth=float(md.measurement_azimuth)))
        return out
    finally:
        m.close_mth5()


# ---------------------------------------------------------------- survey.yaml


def centre_sign(survey: Survey, site: str) -> tuple[int, str]:
    """Return the s of the site from the centre-test table and where it came from.

    Returns:
        tuple: (s, reason): the table's s_obs when the site's verdict is
        "holds", else +1, the prediction.
    """
    table = survey.workspace / CENTRE_TABLE
    if table.exists():
        rows = pd.read_csv(table)
        rows = rows[rows["site"] == site]
        if len(rows):
            row = rows.iloc[0]
            if row["verdict"] == "holds":
                return int(row["s_obs"]), f"s_obs of {table.name} (verdict holds)"
            return 1, f"the prediction +1 ({table.name} verdict {row['verdict']}: no common voltage to read s from)"
    return 1, f"the prediction +1 (no row in {table})"


def survey_entry(survey: Survey, site: str, runs: list[dict], s: int, source: Path, why_s: str,
                 laid: tuple[float, float] | None = None) -> dict:
    """Build the derived site's survey.yaml entry (`ENTRY_KEYS` order; None values left out)."""
    parent = survey.site(site)
    first = runs[0]
    end = pd.Timestamp(runs[-1]["end"]) + pd.Timedelta(seconds=1.0 / first["rate"])  # the span's end, as new_survey.py writes it
    made = dt.datetime.now(dt.timezone.utc).strftime(ISO)
    notes = (f"{site} diagonal ex - ({s:+d}) ey, the centre electrode cancelled, by scripts/diagonal_site.py from "
             f"{source.name}, {made}; s {s:+d} from {why_s}; L_d {first['length']:.3f} m, theta_d "
             f"{first['azimuth']:.3f} deg from magnetic north (EMEAS AZM)"
             + (f"; the rot_e turn undone first (lines laid {laid[0]:g}/{laid[1]:g})" if laid else ""))
    entry = dict(derived_from=site, channels=list(first["channels"]), sample_rate=float(first["rate"]),
                 dipole_length_ex=round(first["length"], 3), azimuth_ex=round(first["azimuth"], 3),
                 latitude=parent.latitude, longitude=parent.longitude, elevation=parent.elevation,
                 declination=parent.declination, declination_model=parent.declination_model,
                 declination_epoch=parent.declination_epoch, start=first["start"], end=iso_utc(end),
                 notes=notes)
    return {k: entry[k] for k in ENTRY_KEYS if entry.get(k) is not None}


def entry_text(name: str, entry: dict, newline: str) -> str:
    """Return the YAML text of one site entry, indented under `sites:` (lists in flow style)."""
    body = yaml.safe_dump({name: entry}, sort_keys=False, default_flow_style=None, width=100, allow_unicode=True)
    return "".join("  " + line + newline for line in body.splitlines())


def comment_count(text: str) -> int:
    """Return the number of lines holding a YAML comment ("#" at the start or after white space)."""
    return sum(1 for line in text.splitlines() if COMMENT.search(line))


def put_entry(text: str, name: str, entry: dict) -> str:
    """Return survey.yaml text with one site entry appended to the sites block or replaced in place.

    Every other line is kept as it is. A new entry goes at the end of the
    sites block (before the next top-level key, or at the end of the file).

    Raises:
        ValueError: If the sites block is not found.
    """
    from declination import entry_spans, sites_block

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    start, end = sites_block(lines)
    spans = entry_spans(lines, start, end)
    block = entry_text(name, entry, newline)
    if name in spans:
        head, stop = spans[name]
        while stop > head + 1 and (not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")):
            stop -= 1  # blank and comment lines at the foot of the entry stay where they are
        return "".join(lines[:head]) + block + "".join(lines[stop:])
    at = end
    while at > start + 1 and not lines[at - 1].strip():
        at -= 1
    return "".join(lines[:at]) + block + "".join(lines[at:])


def check_entry_edit(old: str, new: str, name: str, entry: dict, config_dir: Path) -> list[str]:
    """Compare two survey.yaml texts: only the one site entry may be added or changed.

    Returns:
        list[str]: One line per difference found; empty when the new text is
        the old one with the entry.
    """
    a, b = yaml.safe_load(old) or {}, yaml.safe_load(new) or {}
    found = [f"top-level key {k} changed" for k in set(a) | set(b) if k != "sites" and a.get(k) != b.get(k)]
    sa, sb = a.get("sites") or {}, b.get("sites") or {}
    if [k for k in sa if k != name] != [k for k in sb if k != name]:
        found.append("the other sites or their order changed")
    for site in sa:
        if site != name and sa[site] != sb.get(site):
            found.append(f"{site} changed")
    if sb.get(name) != entry:
        found.append(f"{name} reads back as {sb.get(name)!r}")
    if comment_count(old) != comment_count(new):
        found.append(f"comment lines {comment_count(old)} -> {comment_count(new)}")
    if not found:
        survey = Survey(b, config_dir)
        for site in survey.site_names():
            try:
                survey.site(site)
            except ValueError as exc:
                found.append(f"Survey refuses {site}: {exc}")
        cfg = survey.site(name)
        if survey.parent_of(name) != entry["derived_from"] or [c.lower() for c in cfg.channels] != entry["channels"]:
            found.append(f"Survey reads {name} as derived from {survey.parent_of(name)} with channels {cfg.channels}")
    return found


def add_entry_in_place(path: Path, name: str, entry: dict, dry_run: bool = False) -> tuple[Path | None, list[str]]:
    """Write one derived site's entry into survey.yaml in place, after a copy and the checks.

    Args:
        path (Path): survey.yaml.
        name (str): The derived site.
        entry (dict): Its entry.
        dry_run (bool): Check and report only.

    Returns:
        tuple: (the copy written beside the file, or None when nothing was
        written; the summary lines of the parsed diff).

    Raises:
        ValueError: If the edit changes anything but the entry, the comment
            count changes, or `Survey` refuses a site; the file is left as it was.
    """
    with open(path, encoding="utf-8", newline="") as handle:
        old = handle.read()
    sites = (yaml.safe_load(old) or {}).get("sites") or {}
    if sites.get(name) == entry:
        return None, [f"{name}: the entry is already as written; survey.yaml unchanged"]
    new = put_entry(old, name, entry)
    problems = check_entry_edit(old, new, name, entry, path.parent)
    if problems:
        raise ValueError(f"the survey.yaml edit would change more than {name}'s entry: " + "; ".join(problems))
    summary = [f"parsed diff: {name} {'changed' if name in sites else 'added'}, every other site and top-level key "
               f"equal; comment lines {comment_count(old)} -> {comment_count(new)}; lines {len(old.splitlines())} -> "
               f"{len(new.splitlines())}" + ("; the old file is a byte prefix of the new" if new.startswith(old) else "")]
    if dry_run:
        return None, summary
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.before_diagonal_{name}_{stamp}")
    shutil.copy2(path, backup)
    tmp = path.with_name(f"{path.name}.tmp_diagonal_{name}")
    with open(tmp, "w", encoding="utf-8", newline="") as handle:
        handle.write(new)
    for attempt in range(REPLACE_TRIES):
        with open(path, encoding="utf-8", newline="") as handle:
            if handle.read() != old:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"{path.name} changed while the edit was prepared: nothing written (run it again)")
        try:
            os.replace(tmp, path)
            break
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_WAIT_S)
    return backup, summary


# ---------------------------------------------------------------- the script


def main(argv=None) -> int:
    """Write one site's diagonal archive and register the derived site.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 2 when the site, the name, the chains or the
        survey.yaml edit refuse, 3 when the memory wait runs out.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml")
    parser.add_argument("site", help="the recorded site, e.g. TAS112")
    parser.add_argument("--sign", type=int, choices=(1, -1), default=None,
                        help="s in ex - s ey (default: the centre test's s_obs where the model holds, else +1)")
    parser.add_argument("--force", action="store_true", help="rebuild an existing <site>D.h5 even when current")
    parser.add_argument("--dry-run", action="store_true", help="check and print; write nothing")
    parser.add_argument("--min-free-gb", type=float, default=0.0,
                        help="wait for this much available memory before each run is read (default: no wait)")
    args = parser.parse_args(argv)

    yaml_path = Path(args.survey_yaml).resolve()
    survey = Survey.from_yaml(yaml_path)
    site, name = args.site, derived_name(args.site)
    if site not in survey.site_names():
        print(f"ERROR {site} is not a site of {yaml_path.name}", file=sys.stderr)
        return 2
    if survey.parent_of(site) or survey.bursts_parent(site):
        print(f"ERROR {site} is itself derived: run it on the recorded site", file=sys.stderr)
        return 2
    kept = [c.lower() for c in survey.site(site).channels] if survey.site(site).channels else None
    if kept is not None and not {"ex", "ey"} <= set(kept):
        print(f"ERROR {site} keeps channels {kept}: the diagonal needs both electric lines", file=sys.stderr)
        return 2
    entry = (survey.config.get("sites") or {}).get(name)
    if entry is not None and survey.parent_of(name) != site:
        print(f"ERROR {yaml_path.name} already has a site {name} that is not derived from {site}: not touching it",
              file=sys.stderr)
        return 2
    if args.sign is not None:
        s, why_s = args.sign, "--sign"
    else:
        s, why_s = centre_sign(survey, site)
    out_path = default_archive_path(survey, name)
    source = processing_archive(survey, site)
    laid = archive_rot_e(source, site)
    if laid is not None and survey.instrument_of(site) != "edl":
        print(f"ERROR {site}: its pair was turned at ingest (rot_e, laid {laid[0]:g}/{laid[1]:g}) and the turn is "
              f"undone only at an EDL site (this one is {survey.instrument_of(site)})", file=sys.stderr)
        return 2
    print(f"{name}: ex - ({s:+d}) ey of {source.name} (s from {why_s}) -> {out_path}"
          + (f"; rot_e site (laid {laid[0]:g}/{laid[1]:g}): the turn is undone first" if laid else ""), flush=True)

    reason = None
    if out_path.exists() and not args.force:
        reason = derived_stale(survey, site, out_path)
        recorded = archive_sign(out_path)
        if reason is None and recorded != s:
            reason = f"it was cut with s {recorded}, and s is now {s:+d}"
    if args.dry_run:
        from mth5.mth5 import MTH5

        m = MTH5()
        m.open_mth5(source, mode="r")
        try:
            st = m.get_station(site, survey=m.surveys_group.groups_list[0])
            runs = []
            for run_id, start, end in _real_runs(st):
                run = st.get_run(run_id)
                try:
                    _meta, response, geo = derived_ex(run.get_channel("ex"), run.get_channel("ey"), s, laid)
                    if laid is not None:
                        print(f"  {run_id}{source_lines(run, laid)[2]}")
                except ValueError as exc:
                    print(f"ERROR {site} {run_id}: {exc}", file=sys.stderr)
                    return 2
                fs = float(run.metadata.sample_rate)
                n = int(run.get_channel("ex").hdf5_dataset.shape[0])
                last = pd.Timestamp(str(run.get_channel("ex").metadata.time_period.start)) + pd.Timedelta(
                    seconds=(n - 1) / fs)
                runs.append(dict(id=run_id, start=iso_utc(start), end=iso_utc(last), rate=fs,
                                 channels=["ex"] + [c for c in ("hx", "hy", "hz") if c in run.groups_list], **geo))
                print(f"  {run_id}: chains agree but the dipole (stage {geo['dipole_stage'] + 1}); gains ex "
                      f"{geo['gain_x']:+g}, ey {geo['gain_y']:+g}; L_d {geo['length']:.4f} m, theta_d "
                      f"{geo['azimuth']:.4f} deg; derived chain {[f.name for f in response.filters_list]}")
        finally:
            m.close_mth5()
        state = ("missing" if not out_path.exists() else (f"out of date ({reason})" if reason else "current"))
        print(f"{name}: archive {state}{' (--force rebuilds it)' if args.force else ''}")
    elif out_path.exists() and not args.force and reason is None:
        runs = archive_runs(out_path, name)
        for r in runs:
            r["channels"] = ["ex"] + [c for c in ("hx", "hy", "hz") if c in r["channels"]]
        print(f"{name}: kept {out_path} ({len(runs)} run(s), s {s:+d}); --force rebuilds it")
    else:
        if reason:
            print(f"{name}: {out_path.name} is out of date ({reason}): rebuilding it", flush=True)
        started = time.perf_counter()
        try:
            runs = write_derived(source, site, out_path, s, args.min_free_gb, laid)
        except MemoryError as exc:
            print(f"ERROR {exc}; nothing written", file=sys.stderr)
            return 3
        except ValueError as exc:
            print(f"ERROR {site}: {exc}; nothing written", file=sys.stderr)
            return 2
        print(f"{name}: {len(runs)} run(s) in {time.perf_counter() - started:.0f} s, read back exact; L_d "
              f"{runs[0]['length']:.4f} m, theta_d {runs[0]['azimuth']:.4f} deg")
    new = survey_entry(survey, site, runs, s, source, why_s, laid)
    if entry is not None and args.dry_run is False and not args.force and reason is None and out_path.exists():
        new["notes"] = entry.get("notes", new["notes"])  # a kept archive keeps its entry's notes
    try:
        backup, summary = add_entry_in_place(yaml_path, name, new, dry_run=args.dry_run)
    except ValueError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    for line in summary:
        print(line)
    print(f"{'would write' if args.dry_run else ('wrote' if backup else 'kept')} {name}: {new}")
    if backup:
        print(f"copy before the edit: {backup}")
    if not args.dry_run:
        print(f"archive: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
