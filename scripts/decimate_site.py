# -*- coding: utf-8 -*-
"""
Decimate a site's processing archive into a derived long-period site

An INTERMAGNET observatory (scripts/fetch_observatory.py) records at 1 Hz,
and aurora pairs archives of one sample rate. This script writes a
decimated copy of a broadband site's archive as the derived site
``<site>L`` ("L" for long period), which process_rr.py processes against a
1 Hz remote.

The source is the site's processing archive
(`mt_workbench.ingest.processing_archive`): its filtered variant when filters.yaml
declares filters for it (built first when missing or stale), else its raw
archive. Every run is read one channel at a time and decimated from the
archive rate to --rate (default 1 Hz).

The filter is the one of `mt_workbench.timefreq.decimation_levels`,
scipy.signal.decimate with ftype "fir" and zero_phase, in stages of at most
10 (1000 Hz to 1 Hz: 10, 10, 10), computed in float64. Each stage of factor
q is a Hamming-window FIR of 20q + 1 taps with its cutoff at the stage's
output Nyquist, run as a linear-phase polyphase filter with its delay
removed (scipy.signal.resample_poly), so the phase is zero at every
frequency. From 1000 Hz to 1 Hz its gain is 1.0003 at 100 s, 1.003 at 20 s
and 1.005 at 4 s (the Hamming window's passband ripple), the same on every
channel, so it cancels in an impedance; it is -6 dB at the output Nyquist,
0.5 Hz, and below -53 dB from 0.58 Hz. process_rr.py starts a 1 Hz site's
bands at 4 s. An output sample within the filter's reach of either end of
a run (10q input samples per stage, summed: 11.1 s from 1000 Hz to 1 Hz) is
dropped. Output samples fall on whole UTC seconds: a run starts at the
first whole second at least that reach inside its source run.

The archive, ``<workspace>/mth5/<site>L.h5``, holds station ``<site>L`` in
the source's MTH5 survey, one run per source run (sr1_0002 from
sr1000_0002), each channel in float64 digital counts under the source
channel's metadata and filter chain: dipole length, coil response table,
linear and `lemi423_b_scale` coefficients, azimuth, units. Aurora and
`mt_workbench.timefreq.load_station` calibrate it as they do the source. Each run
comment ("derived_by: decimate_site <version>, from <source> <run> ...")
names the source archive and run, the stages, the source archive's
identity as it was read (``source: <stem> size <bytes> mtime <time>
sha256_head <hex>``, `mt_workbench.ingest.source_note`) and the source run's
own comment. Each run group's `mth5_type` is "Run", as in an archive
`mt_workbench.ingest` writes, so a reader matching that attribute exactly (MANTLE's
MTH5 reader) finds the runs. An existing archive is kept while it is
current (`derived_stale`): the site's processing archive would be the file
its runs record, unchanged, and a filtered variant is current
(`mt_workbench.ingest.variant_ready`). It is rebuilt when the source was
rebuilt or replaced, or its runs record no source (written before the
record); --force rebuilds it in any case.

survey.yaml gains, or has refreshed, the entry
``<site>L: {derived_from, sample_rate, dipole_length_ex/ey, azimuth_ex/ey,
latitude, longitude, elevation, declination, declination_model,
declination_epoch, start, end, notes}`` (the parent's position, dipoles,
azimuths and declination; the derived record's span), with `channels:`
too when the channels the archive holds differ from `defaults:`
(`held_channels`: a parent's own `channels:`, plus hx and hy when it
takes them from a neighbour with `h_from`, as Tasmania's TAS132 does from
TAS131), so that process_rr.py asks aurora for the outputs the archive
has (TAS132L: ex and ey, no hz), through the
survey.yaml writer (`mt_workbench.survey_file.edit`), which changes the
lines of that entry alone and keeps the file as it was in
survey.yaml.previous. A dipole length or azimuth equal to the one in
`defaults:` is left out of the entry, where the site takes it from
`defaults:` all the same.

--min-free-gb G waits, before each source channel is read, until psutil
reports G GB of memory available (polled every 30 s, up to 30 min).
Exit status: 0 done, 2 when the name <site>L is taken by a recorded site or
the site is not a recorded site, 3 when the memory wait runs out.

Usage:
    python scripts/decimate_site.py <survey.yaml> <site> [--rate 1] [--force] [--min-free-gb G]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from loguru import logger  # noqa: E402
from scipy.signal import decimate  # noqa: E402

from mt_workbench.ingest import (  # noqa: E402
    _all_real_run_comments, _file_time_stale, archive_identity, default_archive_path, processing_archive,
    recorded_source, source_note, variant_path, variant_ready,
)
from mt_workbench import __version__ as WORKBENCH_VERSION  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from mt_workbench.timefreq import _real_runs  # noqa: E402

SUFFIX = "L"  # <site>L, the long-period derived site
MAX_STAGE = 10  # largest decimation factor of one FIR stage
MEMORY_POLL_S = 30.0
MEMORY_WAIT_S = 1800.0
ISO = "%Y-%m-%dT%H:%M:%SZ"
NS = 1_000_000_000
# where a derived run comment quotes its source run's comment; the derived run's own
# ``source: `` piece comes before it (`derived_stale`)
SOURCE_RUN_COMMENT = "source run comment: "
# the first piece of a derived run comment, followed by the mt-workbench version: like every
# piece, a dot-free key, one ":" and no ";", since mt_metadata's EMTF XML writer sets each
# "key: value" piece of a run comment as an attribute (docs/upstream_issues.md 48)
DERIVED_BY = "derived_by: decimate_site "


def derived_name(site: str) -> str:
    """Return the derived site's name, ``<site>L``."""
    return f"{site}{SUFFIX}"


def stage_factors(fs_in: float, fs_out: float) -> list[int]:
    """Split the decimation from fs_in to fs_out into stages of at most MAX_STAGE.

    The prime factors of the total factor are packed first-fit, largest
    first, into stages whose product stays within MAX_STAGE; 1000 gives
    [10, 10, 10] and 500 gives [10, 10, 5].

    Args:
        fs_in (float): Archive sample rate in Hz.
        fs_out (float): Output sample rate in Hz.

    Returns:
        list[int]: Stage factors, largest first.

    Raises:
        ValueError: If fs_in / fs_out is not an integer of at least 2, or has
            a prime factor above MAX_STAGE.
    """
    ratio = fs_in / fs_out
    total = int(round(ratio))
    if total < 2 or abs(ratio - total) > 1e-9 * ratio:
        raise ValueError(f"{fs_in:g} Hz to {fs_out:g} Hz is not a whole decimation factor of 2 or more")
    primes, rest, p = [], total, 2
    while rest > 1:
        while rest % p == 0:
            primes.append(p)
            rest //= p
        p += 1
    if max(primes) > MAX_STAGE:
        raise ValueError(f"factor {total} has the prime factor {max(primes)}, above {MAX_STAGE}")
    stages: list[int] = []
    for prime in sorted(primes, reverse=True):
        k = next((i for i, s in enumerate(stages) if s * prime <= MAX_STAGE), None)
        if k is None:
            stages.append(prime)
        else:
            stages[k] *= prime
    return sorted(stages, reverse=True)


def reach_seconds(fs_in: float, stages: list[int]) -> float:
    """Return how far, in s, an output sample's value reaches into the input.

    Each stage of factor q is a 20q + 1 tap FIR, reaching 10q samples of its
    own input rate either side of the output sample.
    """
    reach, fs = 0.0, float(fs_in)
    for q in stages:
        reach += 10 * q / fs
        fs /= q
    return reach


def decimate_array(x: np.ndarray, stages: list[int]) -> np.ndarray:
    """Decimate samples through the FIR stages; output sample j is input sample j * prod(stages).

    Args:
        x (np.ndarray): Samples, float64.
        stages (list[int]): Stage factors (`stage_factors`).

    Returns:
        np.ndarray: The decimated samples, float64.
    """
    for q in stages:
        x = decimate(x, q, n=20 * q, ftype="fir", zero_phase=True)
    return x


def wait_for_memory(min_free_gb: float, what: str) -> None:
    """Wait until psutil reports at least `min_free_gb` GB of available memory.

    Args:
        min_free_gb (float): Threshold in GB; 0 returns at once.
        what (str): What is about to be read, for the log line.

    Raises:
        MemoryError: If the memory is short for MEMORY_WAIT_S seconds.
    """
    if min_free_gb <= 0:
        return
    import psutil

    waited = 0.0
    while True:
        avail = psutil.virtual_memory().available / 1e9
        if avail >= min_free_gb:
            return
        if waited >= MEMORY_WAIT_S:
            raise MemoryError(f"{avail:.1f} GB available after {waited / 60:.0f} min, below --min-free-gb "
                              f"{min_free_gb:g}: stopped before reading {what}")
        if waited == 0.0:
            print(f"  waiting for memory: {avail:.1f} GB available, {min_free_gb:g} GB wanted before {what}",
                  flush=True)
        time.sleep(MEMORY_POLL_S)
        waited += MEMORY_POLL_S


def _metadata_copy(meta):
    """Copy an mt_metadata object through its dict, leaving out its HDF5 reference."""
    values = meta.to_dict(single=True)
    for key in ("hdf5_reference", "mth5_type"):
        values.pop(key, None)
    out = type(meta)()
    out.from_dict(values)
    return out


def _run_metadata(meta):
    """Copy a run group's metadata into a plain mt_metadata Run, less its HDF5 reference and group type.

    A run group updated from it keeps the `mth5_type` "Run" that add_run
    gave it, as `RunGroup.from_runts` keeps it when it takes a RunTS's run
    metadata.
    """
    from mt_metadata.timeseries import Run

    values = meta.to_dict(single=True)
    for key in ("hdf5_reference", "mth5_type"):
        values.pop(key, None)
    out = Run()
    out.from_dict(values)
    return out


def _run_comment(run_group) -> str:
    """Return a run's comment text, "" when there is none."""
    comment = run_group.metadata.comments
    return "" if comment is None else str(getattr(comment, "value", comment) or "")


def run_grid(t0: pd.Timestamp, n: int, fs_in: float, fs_out: float, stages: list[int]) -> dict:
    """Place a run's decimated samples on whole seconds, inside the filter's reach.

    Args:
        t0 (pd.Timestamp): Time of the run's first sample.
        n (int): Number of samples in the run.
        fs_in (float): Run sample rate in Hz.
        fs_out (float): Output sample rate in Hz.
        stages (list[int]): Stage factors.

    Returns:
        dict: ``k0`` (first input sample decimated: the first on a whole
        second), ``offset`` (its distance from the whole second in input
        samples, 0 on a GPS grid), ``first``/``last`` (output samples kept,
        both included; last < first when the run is too short), ``start``
        (UTC time of output sample `first`) and ``reach`` (s).
    """
    t0_ns = pd.Timestamp(t0).value  # ns since the epoch, UTC
    second_ns = -(-t0_ns // NS) * NS
    exact = (second_ns - t0_ns) * fs_in / NS
    k0 = int(round(exact))
    reach = reach_seconds(fs_in, stages)
    first = int(math.ceil(reach * fs_out - 1e-9))
    last = int(math.floor(((n - 1 - k0) / fs_in - reach) * fs_out + 1e-9))
    start = pd.Timestamp(second_ns, unit="ns", tz="UTC") + pd.Timedelta(seconds=first / fs_out)
    return dict(k0=k0, offset=exact - k0, first=first, last=last, start=start, reach=reach)


def write_derived(source: Path, site: str, out_path: Path, rate: float, min_free_gb: float = 0.0) -> list[dict]:
    """Write the decimated copy of a site's archive.

    The source is opened read-only; the output is written under a ``.part``
    name and moved onto `out_path` when every run is written.

    Args:
        source (Path): The site's processing archive.
        site (str): Station id in `source`.
        out_path (Path): Derived archive.
        rate (float): Output sample rate in Hz.
        min_free_gb (float): Memory to wait for before each channel read.

    Returns:
        list[dict]: Per derived run: ``id``, ``source_run``, ``start``,
        ``end`` (UTC ISO), ``n``, ``stages``, ``reach``, ``channels``.

    Raises:
        ValueError: If the source has no run long enough to decimate.
        MemoryError: From `wait_for_memory`.
    """
    from mt_timeseries import ChannelTS
    from mth5.mth5 import MTH5

    name = derived_name(site)
    source_record = source_note(source)  # the source as read, recorded in every run comment
    tmp = out_path.with_name(out_path.name + ".part")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    if tmp.exists():
        tmp.unlink()
    label = f"{int(rate)}" if float(rate).is_integer() else f"{rate:g}".replace(".", "p")
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
        for run_id, t0, _t1 in _real_runs(station_in):
            run_in = station_in.get_run(run_id)
            comps = list(run_in.groups_list)
            first_ch = run_in.get_channel(comps[0])
            fs_in = float(first_ch.metadata.sample_rate)
            n = int(first_ch.hdf5_dataset.shape[0])
            stages = stage_factors(fs_in, rate)
            grid = run_grid(t0, n, fs_in, rate, stages)
            if grid["last"] < grid["first"]:
                logger.warning(f"{site} {run_id}: {n / fs_in:.1f} s is too short for the filter's "
                               f"{grid['reach']:.1f} s reach at each end: left out")
                continue
            if abs(grid["offset"]) > 1e-3:
                logger.warning(f"{site} {run_id}: its samples sit {grid['offset']:+.4f} samples off whole seconds"
                               f"; the nearest sample is taken as the second")
            out_id = f"sr{label}_{run_id.rsplit('_', 1)[-1]}"
            run_out = station_out.add_run(out_id)
            keep = slice(grid["first"], grid["last"] + 1)
            n_out = grid["last"] - grid["first"] + 1
            for comp in comps:
                ch = run_in.get_channel(comp)
                wait_for_memory(min_free_gb, f"{site} {run_id} {comp}")
                started = time.perf_counter()
                x = np.asarray(ch.hdf5_dataset[grid["k0"]:], dtype="float64")
                y = decimate_array(x, stages)[keep]
                del x
                meta = _metadata_copy(ch.metadata)
                meta.sample_rate = rate
                meta.time_period.start = grid["start"].isoformat()
                ts = ChannelTS(meta.type, data=y, channel_metadata=meta)
                ts.channel_response = ch.channel_response
                run_out.from_channel_ts(ts)
                logger.info(f"{site} {run_id} {comp}: {n} samples at {fs_in:g} Hz -> {y.size} at {rate:g} Hz "
                            f"in {time.perf_counter() - started:.1f} s")
            run_out.metadata.update(_run_metadata(run_in.metadata))
            run_out.metadata.id = out_id
            run_out.metadata.sample_rate = rate
            run_out.metadata.comments = (
                f"{DERIVED_BY}{WORKBENCH_VERSION}, from {source.name} {run_id} ({fs_in:g} Hz) to {rate:g} Hz, "
                f"zero-phase FIR stages {stages} (scipy signal decimate), {grid['reach']:.2f} s dropped at each "
                f"end; {source_record}; {SOURCE_RUN_COMMENT}{_run_comment(run_in) or 'none'}"
            )
            run_out.write_metadata()
            run_out.update_metadata()
            end = grid["start"] + pd.Timedelta(seconds=(n_out - 1) / rate)
            runs.append(dict(id=out_id, source_run=run_id, start=grid["start"].strftime(ISO),
                             end=end.strftime(ISO), n=n_out, stages=stages, reach=grid["reach"], channels=comps))
            print(f"  run {out_id} <- {run_id}: {runs[-1]['start']} .. {runs[-1]['end']} ({n_out} samples, "
                  f"{', '.join(comps)})", flush=True)
        if not runs:
            raise ValueError(f"{site}: no run of {source.name} is long enough to decimate")
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
    os.replace(tmp, out_path)
    return runs


def archive_runs(path: Path, station: str) -> list[dict]:
    """List the runs of an existing derived archive, opened read-only: ``id``, ``start``, ``end``, ``rate``."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        st = m.get_station(station, survey=m.surveys_group.groups_list[0])
        out = []
        for run_id, start, end in _real_runs(st):
            run = st.get_run(run_id)
            out.append(dict(id=run_id, start=start.strftime(ISO), end=end.strftime(ISO),
                            rate=float(run.metadata.sample_rate), channels=list(run.groups_list)))
        return out
    finally:
        m.close_mth5()


def derived_stale(survey: Survey, site: str, out_path: Path) -> str | None:
    """Say why an existing derived archive is out of date with its source.

    The source is the archive `processing_archive` would give for the
    site: its filtered variant when filters.yaml declares filters for it,
    else its raw archive. The derived archive is out of date when the
    variant is not current (`mt_workbench.ingest.variant_ready`, which also
    covers a rebuilt raw archive), a derived run's comment records no
    source identity, or the recorded identity is not the source's as it is
    now (`mt_workbench.ingest.archive_identity`). A raw archive that is
    missing is not judged, as `variant_ready` does not judge one: the
    derived archive still holds what it was cut from. A derived archive
    none of whose runs records its source (cut before the record of 5 Oct
    2026) is judged by file times (`mt_workbench.ingest._file_time_stale`):
    current, with a warning, when it is newer than the source.

    Args:
        survey (Survey): The survey.
        site (str): The recorded site.
        out_path (Path): Its existing derived archive.

    Returns:
        str or None: The reason; None when the archive is current.
    """
    if survey.site(site).filters:
        if not variant_ready(survey, site):
            return f"{site}'s filtered variant is missing or out of date and is rebuilt first"
        source = variant_path(survey, site)
    else:
        source = default_archive_path(survey, site)
        if not source.exists():
            return None
    comments = _all_real_run_comments(out_path) or []
    if not comments:
        return "it holds no run"
    recorded_runs = [recorded_source(c, stop=SOURCE_RUN_COMMENT) for c in comments]
    if not any(recorded_runs):
        why = _file_time_stale(out_path, [source])
        if why is None:
            logger.warning(f"{derived_name(site)}: {out_path.name} records no source archive (cut before "
                           f"archives recorded their source): judged current by file time, newer than {source.name}; "
                           f"it will carry the record when next rebuilt")
        return why
    now = archive_identity(source)
    for recorded in recorded_runs:
        if recorded is None:
            return "some of its runs record no source archive"
        if recorded != now:
            return f"it was cut from {recorded}, and the source is now {now}"
    return None


CHANNEL_ORDER = ("ex", "ey", "hx", "hy", "hz")  # the order a derived entry's `channels:` is written in


def held_channels(survey: Survey, site: str) -> list[str] | None:
    """Return the channels a recorded site's archive holds by its declaration, for its derived entry.

    The site's `channels:` (merged with `defaults:`), plus hx and hy when
    it takes them from a neighbour (`h_from`): the ingest writes the
    borrowed coils into its archive, so the derived archive holds them as
    its own. None when the site declares no channels (every column kept).

    Args:
        survey (Survey): The survey.
        site (str): The recorded site.

    Returns:
        list[str] | None: Lower-case channel names in `CHANNEL_ORDER`.
    """
    config = survey.site(site)
    if not config.channels:
        return None
    held = [str(c).lower() for c in config.channels]
    if config.h_from:
        held += [c for c in ("hx", "hy") if c not in held]
    return sorted(held, key=lambda c: CHANNEL_ORDER.index(c) if c in CHANNEL_ORDER else len(CHANNEL_ORDER))


def survey_entry(survey: Survey, site: str, rate: float, runs: list[dict], notes: str) -> dict:
    """Build the derived site's survey.yaml entry.

    Args:
        survey (Survey): The survey.
        site (str): The parent site.
        rate (float): Derived sample rate in Hz.
        runs (list[dict]): The derived runs (``start``, ``end``).
        notes (str): The entry's notes.

    Returns:
        dict: derived_from, sample_rate, `channels` when the archive's
        (`held_channels`) differ from `defaults:`, the parent's dipoles,
        azimuths, position and declination (value, model, epoch; left out
        when the parent has none), the record's start and end (end: the
        last sample plus one sample interval, as new_survey.py writes a
        span) and notes.
    """
    parent = survey.site(site)
    end = pd.Timestamp(runs[-1]["end"]) + pd.Timedelta(seconds=1.0 / rate)
    held = held_channels(survey, site)
    default = [str(c).lower() for c in (survey.defaults.get("channels") or [])]
    channels = held if held is not None and sorted(held) != sorted(default) else None
    entry = dict(derived_from=site, sample_rate=float(rate), channels=channels,
                 dipole_length_ex=parent.dipole_length_ex, dipole_length_ey=parent.dipole_length_ey,
                 azimuth_ex=parent.azimuth_ex, azimuth_ey=parent.azimuth_ey,
                 latitude=parent.latitude, longitude=parent.longitude, elevation=parent.elevation,
                 declination=parent.declination, declination_model=parent.declination_model,
                 declination_epoch=parent.declination_epoch,
                 start=runs[0]["start"], end=end.strftime(ISO), notes=notes)
    return {k: v for k, v in entry.items() if v is not None}


def main(argv=None) -> int:
    """Decimate one site and register the derived site.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    An existing derived archive is kept unless `derived_stale` gives a
    reason, which is printed before the rebuild, or --force is given.

    Returns:
        int: 0 on success, 2 when the site or the derived name does not
        fit, 3 when the memory wait runs out.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml")
    parser.add_argument("site", help="the recorded site to decimate, e.g. B01")
    parser.add_argument("--rate", type=float, default=1.0, help="output sample rate in Hz (default %(default)g)")
    parser.add_argument("--force", action="store_true", help="rebuild an existing <site>L.h5 even when current")
    parser.add_argument("--min-free-gb", type=float, default=0.0,
                        help="wait for this much available memory before each channel read (default: no wait)")
    args = parser.parse_args(argv)

    yaml_path = Path(args.survey_yaml).resolve()
    survey = Survey.from_yaml(yaml_path)
    site, name = args.site, derived_name(args.site)
    if survey.parent_of(site):
        print(f"ERROR {site} is itself derived from {survey.parent_of(site)}: decimate {survey.parent_of(site)}",
              file=sys.stderr)
        return 2
    entry = (survey.config.get("sites") or {}).get(name)
    if entry is not None and survey.parent_of(name) != site:
        print(f"ERROR {yaml_path.name} already has a site {name} that is not derived from {site}: not touching it",
              file=sys.stderr)
        return 2
    out_path = default_archive_path(survey, name)

    stale = derived_stale(survey, site, out_path) if out_path.exists() and not args.force else None
    if stale:
        print(f"{name}: {out_path.name} is out of date ({stale}): rebuilding it", flush=True)
    if out_path.exists() and not args.force and not stale:
        runs = archive_runs(out_path, name)
        rate = runs[0]["rate"]
        notes = (entry or {}).get("notes") or f"{site} decimated to {rate:g} Hz by scripts/decimate_site.py"
        print(f"{name}: kept {out_path} ({len(runs)} run(s) at {rate:g} Hz); --force rebuilds it")
    else:
        rate = args.rate
        source = processing_archive(survey, site)
        print(f"{name}: decimating {source} to {rate:g} Hz -> {out_path}", flush=True)
        started = time.perf_counter()
        try:
            runs = write_derived(source, site, out_path, rate, args.min_free_gb)
        except MemoryError as exc:
            print(f"ERROR {exc}; nothing written", file=sys.stderr)
            return 3
        print(f"{name}: {len(runs)} run(s) in {time.perf_counter() - started:.0f} s; stages {runs[0]['stages']}, "
              f"{runs[0]['reach']:.2f} s dropped at each run end")
        made = dt.datetime.now(dt.timezone.utc).strftime(ISO)
        notes = f"{site} decimated to {rate:g} Hz from {source.name} by scripts/decimate_site.py, {made}"

    from mt_workbench import survey_file  # the survey.yaml writer: one entry changed, the rest as it was

    new = survey_entry(survey, site, rate, runs, notes)
    if name in (survey.config.get("sites") or {}):
        survey_file.edit(yaml_path, sites={name: new})
    else:
        survey_file.edit(yaml_path, add={name: new})
    print(f"{'refreshed' if entry else 'added'} {name} in {yaml_path}: {new}")
    print(f"archive: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
