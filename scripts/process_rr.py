"""Ingest a local and a remote site, estimate the remote-referenced TF, and
overlay it on the legacy lemimt EDI when the survey maps one.

Usage:
    python scripts/process_rr.py <survey.yaml> <local> <remote> [start] [end]

Each site's whole deployment is ingested once (one MTH5 per site holds all its
runs; later runs against other partners reuse it). `start`/`end` (UTC, e.g.
"2018-06-22 21:40") are a *processing window* applied to the aurora kernel
dataset, not to the archive — use them to keep a bad stretch out of the
estimate (Burra35's Ex died 16.5 h in). Without them aurora works on the full
time overlap. Long deployments are split into runs of at most MAX_RUN_FILES
files to bound memory; at 90 min per file that is still ~2 days per run.

Outputs: <workspace>/mth5/<site>.h5, <workspace>/tf/<tag>.edi and
<workspace>/tf/<tag>_vs_lemimt.png, where <tag> is <local>_rr-<remote> plus a
compact window suffix when a window was given.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd
import yaml
from loguru import logger

from bbmt.bands import lemimt_band_scheme
from bbmt.compare import phase_quadrants, plot_comparison
from bbmt.ingest import ingest_site
from bbmt.process import process_station
from bbmt.survey import Survey

MAX_RUN_FILES = 34  # 34 x 90 min = 51 h per run


def reference_edi(survey_yaml: Path, site: str):
    ref_yaml = Path(survey_yaml).parent / "reference_edis.yaml"
    if not ref_yaml.exists():
        return None
    mapping = yaml.safe_load(ref_yaml.read_text(encoding="utf-8")) or {}
    return (mapping.get(site) or {}).get("edi")


def main(survey_yaml: str, local: str, remote: str, start=None, end=None) -> None:
    survey = Survey.from_yaml(survey_yaml)
    raw_sites = survey.site_dirs()
    for site in (local, remote):
        if site not in raw_sites:
            continue
        cfg = survey.site(site)
        logger.info(
            f"{site}: Ex {cfg.dipole_length_ex} m @ {cfg.azimuth_ex} deg, "
            f"Ey {cfg.dipole_length_ey} m @ {cfg.azimuth_ey} deg, timing {cfg.timing}"
        )
    local_h5 = ingest_site(survey, local, max_run_files=MAX_RUN_FILES)
    # a stacked synthetic remote (scripts/build_stack.py) has no raw folder:
    # use its archive as it is
    virtual_h5 = survey.workspace / "mth5" / f"{remote}.h5"
    if remote not in raw_sites and virtual_h5.exists():
        logger.info(f"{remote}: virtual remote, using {virtual_h5}")
        remote_h5 = virtual_h5
    else:
        remote_h5 = ingest_site(survey, remote, max_run_files=MAX_RUN_FILES)

    tag = f"{local}_rr-{remote}"
    if start or end:
        fmt = lambda t: pd.Timestamp(t).strftime("%Y%m%dT%H%M") if t else "open"
        tag += f"_w{fmt(start)}-{fmt(end)}"
    scheme = lemimt_band_scheme(survey.sample_rate, **survey.processing)
    tf = process_station(
        local_h5, local, remote_h5, remote,
        out_dir=survey.workspace / "tf", band_scheme=scheme,
        start=start, end=end, tag=tag,
    )

    q = phase_quadrants(tf)
    msg = f"{local}: short-period phases xy {q['xy']:+.0f} deg, yx {q['yx']:+.0f} deg"
    if q["xy_ok"] and q["yx_ok"]:
        logger.info(msg + " (physical quadrants)")
    else:
        logger.error(
            msg + " — a mode is 180 deg out: an E or H channel has the wrong sign. "
            "Check dipole polarity (flip_reversed_dipoles in survey.yaml) and re-ingest."
        )

    baseline = reference_edi(Path(survey_yaml), local)
    if baseline is None:
        logger.warning(f"{local}: no reference EDI mapped — plotting aurora alone")
    window = f"{start or 'start'} to {end or 'end'} UTC" if (start or end) else "full overlap"
    out_png = survey.workspace / "tf" / f"{tag}_vs_lemimt.png"
    plot_comparison(
        tf, baseline=baseline,
        title=f"{local} RR {remote} — aurora vs lemimt ({window})",
        out_png=out_png,
    )
    print(f"comparison figure: {out_png}")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    main(*sys.argv[1:6])
