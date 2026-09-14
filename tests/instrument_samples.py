"""The one-hour LEMI-424 and EDL samples the instrument tests share -- a helper, not a test.

Cut from two real stations, read only, into the scratch folder (never the
whole station):

    samples/MBJ21     LEMI-424, a 2024 WA-MT site: its deployment
                      `.inf` and the first 3600 lines (2024-10-25 00:00:00 to
                      00:59:59 UTC, 1 Hz) of the daily file 202410250000.txt
    samples/EGFLP02   Earth Data PR6-24, Eastern Goldfields long period (10 Hz):
                      config/recorder.ini and the hour 2019-01-10 00:00 UTC,
                      010/EGFLP02_190110000000.{BX,BY,BZ,EX,EY}

`mixed_survey()` puts both beside a synthetic LEMI-423 site (S01, written by
`tests/new_survey_unit.py`'s `write_b423`) in `mixed_root/`, runs
`scripts/new_survey.py` over it into `mixed/survey.yaml` (workspace
`mixed_root/work`), and `ensure_archives()` ingests MBJ21 and EGFLP02 into
that workspace when their archives are missing -- the survey the GUI smoke
test opens. A missing source drive is an error, not a skip.
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
    """{site: folder} of the two one-hour samples, cut from the sources when not already there."""
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
    """`mixed_root/`: S01 (synthetic LEMI-423, three 2 s files) + the two samples; `work/` kept."""
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
    """scripts/new_survey.py over `mixed_root()` into MIXED_YAML (--force), its output captured."""
    root = mixed_root()
    return subprocess.run([sys.executable, str(REPO / "scripts" / "new_survey.py"), str(root), "--name", "mixed",
                           "--out", str(MIXED_YAML), "--force", *extra],
                          cwd=REPO, capture_output=True, text=True)


def ensure_archives(sites=("MBJ21", "EGFLP02")) -> dict[str, Path]:
    """The mixed survey's archives of `sites`, ingested (`mtproc.ingest.ingest_site`) when missing."""
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
