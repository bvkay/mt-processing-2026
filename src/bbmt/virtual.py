"""Synthetic (stacked) remote-reference stations.

Builds a virtual station whose hx/hy are the mean of several concurrent
sites' raw magnetic counts. No calibration is applied or declared: the RR
estimator is invariant to any linear transform of the remote channels, so
only coherence with the true field matters. Sample grids must align exactly
(GPS-locked 1 ms grids with integer-second file starts); this is asserted,
not assumed.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from loguru import logger
from mth5.mth5 import MTH5

from .ingest import _group_contiguous, _keep_channels, read_lemi423, select_files
from .noise import apply_filters
from .survey import Survey


def _member_dataset(survey: Survey, site_name: str, start, end):
    """Read one member's largest contiguous in-window run; return hx/hy dataset.

    A member's declared filters (`<survey>/filters.yaml`: notch, cp) are
    applied to its raw counts before stacking, so a site whose coils are
    swamped by mains can still contribute (`replace` entries are ignored here).
    """
    site_dir = survey.site_dirs()[site_name]
    files = select_files(site_dir, start, end)
    groups = _group_contiguous(files)
    group = max(groups, key=len)
    if len(groups) > 1:
        logger.info(
            f"{site_name}: using longest of {len(groups)} contiguous groups "
            f"({len(group)}/{len(files)} files)"
        )
    run = read_lemi423(group if len(group) > 1 else group[0], station_id=site_name)
    cfg = survey.site(site_name)
    _keep_channels(run, cfg)
    specs = [s for s in (cfg.filters or []) if "replace" not in s]
    if specs:
        apply_filters(run, specs, float(run.sample_rate), tag=f"stack member {site_name}")
    return run.dataset[["hx", "hy"]]


def build_synthetic_remote(
    survey: Survey,
    members,
    start,
    end,
    name: str = "SYN01",
    out_path: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Stack members' raw hx/hy into a virtual station MTH5.

    `members` is a list of sites used for both coils, or a dict
    ``{"hx": [...], "hy": [...]}`` with a member list per coil — the
    coherence-selected stack: a site whose hy is dead can still lend its hx
    (Burra01), and vice versa (Burra37). Each coil is the plain mean of its
    members over the common span.
    """
    out_path = Path(out_path) if out_path else survey.workspace / "mth5" / f"{name}.h5"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        if not overwrite:
            logger.info(f"{out_path} exists — reusing (overwrite=False)")
            return out_path
        out_path.unlink()

    per_comp = members if isinstance(members, dict) else {"hx": list(members), "hy": list(members)}
    per_comp = {c: list(v) for c, v in per_comp.items()}
    all_members = sorted(set(per_comp["hx"]) | set(per_comp["hy"]))
    datasets = {m: _member_dataset(survey, m, start, end) for m in all_members}

    # common span over every member used, then exact grid identity
    t0 = max(ds.time.values[0] for ds in datasets.values())
    t1 = min(ds.time.values[-1] for ds in datasets.values())
    if t1 <= t0:
        raise ValueError(f"{name}: members do not overlap in [{start}, {end})")
    for m in all_members:
        datasets[m] = datasets[m].sel(time=slice(t0, t1))
    ref = datasets[all_members[0]]
    for m in all_members[1:]:
        ds = datasets[m]
        if ds.time.size != ref.time.size or not np.array_equal(ds.time.values, ref.time.values):
            raise ValueError(
                f"{m}: sample grid does not align with the stack "
                f"(sizes {ds.time.size} vs {ref.time.size}) — GPS timing "
                f"assumption violated, investigate before stacking"
            )
    total = ref[["hx", "hy"]].astype("float64").copy(deep=True)
    for comp in ("hx", "hy"):
        acc = np.zeros(ref.time.size, dtype="float64")
        for m in per_comp[comp]:
            acc += datasets[m][comp].data.astype("float64")
        total[comp].data = acc / len(per_comp[comp])
        # virtual station carries no filters: RR is calibration-invariant
        total[comp].attrs["filters"] = []
        total[comp].attrs["station.id"] = name
        total[comp].attrs["units"] = "digital counts"
        logger.info(f"{name}: {comp} = mean of {per_comp[comp]} ({ref.time.size} samples)")
    members = all_members

    # centroid location for metadata
    lats = [survey.site(m).latitude for m in members if survey.site(m).latitude]
    lons = [survey.site(m).longitude for m in members if survey.site(m).longitude]

    m = MTH5(file_version="0.2.0")
    m.open_mth5(out_path, mode="w")
    try:
        m.add_survey(survey.name)
        station_group = m.add_station(name, survey=survey.name)
        if lats and lons:
            station_group.metadata.location.latitude = float(np.mean(lats))
            station_group.metadata.location.longitude = float(np.mean(lons))
        station_group.metadata.comments = (
            f"synthetic remote: mean of raw hx/hy counts from {', '.join(members)}; "
            f"uncalibrated by design (RR estimator is calibration-invariant)"
        )
        station_group.write_metadata()

        run_group = station_group.add_run("sr1000_0001")
        for comp in ("hx", "hy"):
            da = total[comp]
            ch = run_group.add_channel(
                comp,
                "magnetic",
                da.data.astype("float32"),
                channel_dtype="float32",
            )
            ch.metadata.component = comp
            ch.metadata.sample_rate = float(survey.sample_rate)
            ch.metadata.time_period.start = str(np.datetime_as_string(da.time.values[0])) + "+00:00"
            ch.metadata.time_period.end = str(np.datetime_as_string(da.time.values[-1])) + "+00:00"
            ch.metadata.units = "digital counts"
            ch.metadata.measurement_azimuth = 0.0 if comp == "hx" else 90.0
            ch.write_metadata()
        run_group.metadata.sample_rate = float(survey.sample_rate)
        run_group.metadata.time_period.start = str(np.datetime_as_string(total.time.values[0])) + "+00:00"
        run_group.metadata.time_period.end = str(np.datetime_as_string(total.time.values[-1])) + "+00:00"
        run_group.write_metadata()
        station_group.metadata.time_period.start = run_group.metadata.time_period.start
        station_group.metadata.time_period.end = run_group.metadata.time_period.end
        station_group.write_metadata()
    finally:
        m.close_mth5()
    logger.info(f"{name}: wrote {out_path}")
    return out_path
