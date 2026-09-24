# -*- coding: utf-8 -*-
"""
One-hour LEMI-424 and EDL samples shared by the instrument tests

A helper module for the tests. It cuts one hour from each of two real
stations into the scratch folder, reading the sources read-only:

    samples/MBJ21     LEMI-424, a 2024 WA-MT site: its deployment
                      `.inf` and the first 3600 lines (2024-10-25 00:00:00 to
                      00:59:59 UTC, 1 Hz) of the daily file 202410250000.txt
    samples/EGFLP02   Earth Data PR6-24, Eastern Goldfields long period (10 Hz):
                      config/recorder.ini and the hour 2019-01-10 00:00 UTC,
                      010/EGFLP02_190110000000.{BX,BY,BZ,EX,EY}

`mixed_survey()` puts both beside a synthetic LEMI-423 site (S01, written by
`write_b423` in `tests/new_survey_unit.py`) in `mixed_root/` and runs
`scripts/new_survey.py` over it into `mixed/survey.yaml` (workspace
`mixed_root/work`). `ensure_archives()` ingests MBJ21 and EGFLP02 into that
workspace when their archives are missing. This is the survey the GUI smoke
test opens. A missing source drive stops the calling test with a FAIL.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from _scratch import scratch_dir

REPO = Path(__file__).resolve().parents[1]
SCRATCH = scratch_dir("instruments")
LEMI424_SOURCE = Path(r"E:\MT_Timeseries_DATA\MT_WA-MT\Phase_1\!TimeSeries_ByName_1stDataRelease\MBJ21")
EDL_SOURCE = Path(r"D:\MT_PROCESSING_2026\MT_Processing\MT_EasternGoldfields\EGFLP02")
LEMI424_FILE, LEMI424_INF, LEMI424_LINES = "202410250000.txt", "202410240824.inf", 3600
EDL_STAMP, EDL_DAY = "EGFLP02_190110000000", "010"
EDL_CHANNELS = ("BX", "BY", "BZ", "EX", "EY")
MIXED_ROOT, MIXED_YAML = SCRATCH / "mixed_root", SCRATCH / "mixed" / "survey.yaml"
SYNTHETIC_SITE = "S01"


def make_samples(root: Path = SCRATCH / "samples") -> dict[str, Path]:
    """Return the folders of the two one-hour samples, cutting them if needed.

    Args:
        root (Path): Folder that holds the samples.

    Returns:
        dict[str, Path]: Sample folder by site name (MBJ21, EGFLP02).

    Raises:
        SystemExit: When a source station folder is not mounted.
    """
    for source in (LEMI424_SOURCE, EDL_SOURCE):
        if not source.is_dir():
            raise SystemExit(f"FAIL: {source} is not mounted: the instrument samples cannot be made")
    lemi, edl = root / "MBJ21", root / "EGFLP02"
    if not (lemi / LEMI424_FILE).exists():
        lemi.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEMI424_SOURCE / LEMI424_INF, lemi / LEMI424_INF)
        with open(LEMI424_SOURCE / LEMI424_FILE, "rb") as src:
            head = b"".join(src.readline() for _ in range(LEMI424_LINES))
        (lemi / LEMI424_FILE).write_bytes(head)
    if not all((edl / EDL_DAY / f"{EDL_STAMP}.{c}").exists() for c in EDL_CHANNELS):
        (edl / "config").mkdir(parents=True, exist_ok=True)
        (edl / EDL_DAY).mkdir(parents=True, exist_ok=True)
        shutil.copy2(EDL_SOURCE / "config" / "recorder.ini", edl / "config" / "recorder.ini")
        for c in EDL_CHANNELS:
            shutil.copy2(EDL_SOURCE / EDL_DAY / f"{EDL_STAMP}.{c}", edl / EDL_DAY / f"{EDL_STAMP}.{c}")
    return {"MBJ21": lemi, "EGFLP02": edl}


def mixed_root() -> Path:
    """Rebuild the site folders of `mixed_root/`.

    Writes S01 (synthetic LEMI-423, three 2 s files) and copies in the two
    samples. The `work/` folder is kept.

    Returns:
        Path: MIXED_ROOT.
    """
    sys.path.insert(0, str(REPO / "tests"))
    from new_survey_unit import SITES, write_b423

    samples = make_samples()
    for name in ("S01", "MBJ21", "EGFLP02"):
        shutil.rmtree(MIXED_ROOT / name, ignore_errors=True)
    folder, sub, serial, fw, lat, lon, alt, epoch, spacing, n = SITES[0]
    for k in range(n):
        write_b423(MIXED_ROOT / SYNTHETIC_SITE / sub / f"{epoch + k * spacing}.B423", serial, fw, lat, lon, alt,
                   epoch + k * spacing)
    for site, source in samples.items():
        shutil.copytree(source, MIXED_ROOT / site)
    return MIXED_ROOT


def mixed_survey(*extra: str) -> subprocess.CompletedProcess:
    """Run scripts/new_survey.py over `mixed_root()` into MIXED_YAML with --force.

    Args:
        *extra (str): Further command-line arguments for new_survey.py.

    Returns:
        subprocess.CompletedProcess: The finished run, with stdout and stderr
        captured as text.
    """
    root = mixed_root()
    return subprocess.run([sys.executable, str(REPO / "scripts" / "new_survey.py"), str(root), "--name", "mixed",
                           "--out", str(MIXED_YAML), "--force", *extra],
                          cwd=REPO, capture_output=True, text=True)


def ensure_archives(sites=("MBJ21", "EGFLP02")) -> dict[str, Path]:
    """Return the mixed survey's archives of `sites`, ingesting missing ones.

    Builds the mixed survey first if MIXED_YAML does not exist. Missing
    archives are written with `mtproc.ingest.ingest_site`.

    Args:
        sites (tuple[str, ...]): Site names.

    Returns:
        dict[str, Path]: Archive path by site name.
    """
    sys.path.insert(0, str(REPO / "src"))
    from mtproc.ingest import default_archive_path, ingest_site
    from mtproc.survey import Survey

    if not MIXED_YAML.exists():
        done = mixed_survey()
        assert done.returncode == 0, done.stdout + done.stderr
    survey = Survey.from_yaml(MIXED_YAML)
    out = {}
    for site in sites:
        path = default_archive_path(survey, site)
        out[site] = path if path.exists() else ingest_site(survey, site)
    return out
