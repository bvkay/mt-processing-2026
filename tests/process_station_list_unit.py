# -*- coding: utf-8 -*-
"""
Unit test for the Process tab's station list (`State.station_choices`) and process_rr's recorded remotes

Runs headless. A scratch survey declares sites with raw folders, archives,
both or neither, a derived site, two burst sites, an observatory, and has a
raw folder and a stack archive it does not declare. `MainWindow` is built
on it and the Process tab's station combo is read back, first with the raw
folders under `data_root`, then with `data_root` stale in its two forms: an
existing folder that holds no site folder (the Atlas survey's data root
after its raw data moved to another drive) and a folder that does not exist (a drive not plugged in).
Under each stale root `ingest_site` is called for a site whose archive
exists and one with none. Then scripts/process_rr.py's `resolve` is run on
recorded remotes that declare filters (workbench issue 32) and on virtual
remotes (a stack, a burst site, a derived site, an observatory) under the
three roots. Last, if the Atlas survey and its workspace are reachable,
`MainWindow` is built on its survey.yaml (read only; another survey.yaml,
such as a copy whose `data_root` is on another drive, with `--atlas PATH`) and the
station list is compared with the list made from the survey.yaml text, the
raw folders under its `data_root` and the workspace's `mth5/` folder.

Usage:
    QT_QPA_PLATFORM=offscreen MT_WORKBENCH_TEST_SCRATCH=<own folder> python tests/process_station_list_unit.py
        [--atlas <survey.yaml>]

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**, with the raw folders present, the station combo is
not exactly S01, S01H "(bursts of S01, 24000 Hz)", S01L "(derived from S01,
1 Hz)", S02, S03 "(archive)", S03H and U01 in that order, labels as given
and data the plain names: a raw folder (declared or not, archived or not)
loses its place or gains a mark, S04 (declared, neither raw folder nor
archive), OBS (an observatory) or STK_X (an archive not declared) is
listed; or, under either stale root, `State.raw_sites()` is not empty, the
combo is not exactly S01 "(archive)", S01H, S01L, S03 "(archive)", S03H; or
then S03 with remote S01 does not enable Add to queue and queue
process_rr.py for S03 rr-S01, or the remote combo labels S01 other than
"S01  (archive)" or STK_X other than "STK_X  (stack)"; or `ingest_site` on
a stale survey does not return S03's archive untouched, or does not raise
FileNotFoundError naming S04's missing raw folder; or process_rr's
`resolve` takes S01 or S03 (declared, filters declared) as a virtual
remote, gives no archive status or variant for it, or records filters
other than its declaration, or gives any different decision under the
three roots; or a stack (STK_X), a burst site (S03H), a derived site (S01L)
or an observatory (OBS) as the remote is not virtual with no filter
record; or on the Atlas survey the station list is not the raw folders
under its `data_root` with the declared, non-observatory sites that have an
archive, a raw folder listed plain and every other site labelled by its
kind ("(archive)", "(derived from ...", "(bursts of ..."), or lists B30 or
B31 (archives not declared) without a raw folder of that name,
or EBR or SPT (observatories); or any Qt slot raised. Mutations that trip
it: the station list built from `State.raw_sites()` alone; process_rr's
`recorded_site_folders` reduced to the raw folders found.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import re
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from mt_workbench.gui.app import MainWindow, State  # noqa: E402
from mt_workbench.gui.jobs import JobRunner  # noqa: E402

SCRATCH = scratch_dir("process_station_list_unit")
ATLAS_YAML = REPO / "surveys" / "MT_Morocco_Atlas_Mountains" / "survey.yaml"

# a job the window would start at once (a basemap fetch) is recorded, not run
STARTED: list[list[str]] = []
JobRunner.run_now = lambda self, label, argv, **details: STARTED.append([str(a) for a in argv]) or -1

SLOT_ERRORS: list[str] = []


def _record_slot_error(exc_type, exc, tb) -> None:
    """Record an exception raised inside a Qt slot; `main` fails at the end when any were."""
    import traceback

    SLOT_ERRORS.append("".join(traceback.format_exception(exc_type, exc, tb)))
    sys.stderr.write(SLOT_ERRORS[-1])


sys.excepthook = _record_slot_error

SITES = {
    "S01": {"latitude": -31.0, "longitude": 140.0},   # raw folder and archive
    "S02": {"latitude": -31.0, "longitude": 140.01},  # raw folder only: it can be ingested
    "S03": {"latitude": -31.0, "longitude": 140.02},  # archive only
    "S04": {"latitude": -31.0, "longitude": 140.03},  # neither
    "S01L": {"derived_from": "S01", "sample_rate": 1.0},  # derived, archived
    "S02L": {"derived_from": "S02", "sample_rate": 1.0},  # derived, not decimated yet
    "S01H": {"bursts_of": "S01", "sample_rate": 24000},  # burst sites, archived
    "S03H": {"bursts_of": "S03", "sample_rate": 24000},
    "OBS": {"instrument": "intermagnet", "latitude": -30.0, "longitude": 139.0},  # an observatory, archived
}
RAW_FOLDERS = ("S01", "S02", "U01")  # U01: a raw folder survey.yaml does not declare
# STK_X: a stack; the last a filtered variant
ARCHIVES = ("S01", "S03", "S01L", "S01H", "S03H", "OBS", "STK_X", "S03_f0123abcd")

WITH_RAW = [("S01", "S01"), ("S01H  (bursts of S01, 24000 Hz)", "S01H"), ("S01L  (derived from S01, 1 Hz)", "S01L"),
            ("S02", "S02"), ("S03  (archive)", "S03"), ("S03H  (bursts of S03, 24000 Hz)", "S03H"), ("U01", "U01")]
STALE = [("S01  (archive)", "S01"), ("S01H  (bursts of S01, 24000 Hz)", "S01H"),
         ("S01L  (derived from S01, 1 Hz)", "S01L"), ("S03  (archive)", "S03"),
         ("S03H  (bursts of S03, 24000 Hz)", "S03H")]
# the stale roots: an existing folder with no site folder in it (a stray recorder file and a
# folder of notes, as the Atlas D: folder holds), and a folder that does not exist
MOVED, UNMOUNTED = "moved_away", "drive_not_mounted"

# the filters the recorded remotes declare, for the issue-32 case
FILTERS = {"S01": [{"mains": {"f0": 50.0, "harmonics": 9, "block_s": 1.0, "step_fraction": 0.3}}],
           "S03": [{"notch": {"f0": 50.0, "harmonics": 3, "q": 30.0, "passes": 2}}]}
SPAN = {"start": "2023-07-11T00:00:00Z", "end": "2023-07-13T00:00:00Z"}
RECORDED_PAIRS = (("S03", "S01"), ("S01", "S03"))
VIRTUAL_PAIRS = (("S01", "STK_X"), ("S01H", "S03H"), ("S02L", "S01L"), ("S01L", "OBS"))


def make_survey() -> Path:
    """Write the scratch survey: raw folders with one empty B423 file each, archives as empty files.

    The stale root `MOVED` is written too: a stray B423 file and a folder
    of notes, no site folder.

    Returns:
        Path: The survey.yaml.
    """
    root = SCRATCH / "survey"
    if root.exists():
        shutil.rmtree(root)
    raw, work = root / "raw", root / "work"
    for name in RAW_FOLDERS:
        (raw / name).mkdir(parents=True)
        (raw / name / "1689097421.B423").write_bytes(b"")
    (root / MOVED / "Field_Notes").mkdir(parents=True)
    (root / MOVED / "1689097421.B423").write_bytes(b"")
    (work / "mth5").mkdir(parents=True)
    (work / "basemap.json").write_text("{}", encoding="utf-8")  # no basemap fetch on open
    for name in ARCHIVES:
        (work / "mth5" / f"{name}.h5").write_bytes(b"")
    config = {"name": "station_list", "instrument": "lemi423", "sample_rate": 1000,
              "data_root": str(raw), "workspace": str(work), "sites": SITES}
    path = root / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def set_data_root(path: Path, data_root: Path) -> None:
    """Point the survey's `data_root` at `data_root`."""
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["data_root"] = str(data_root)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")


def pump(app: QApplication, seconds: float = 0.1) -> None:
    """Process Qt events for `seconds`."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


def combo_items(combo) -> list[tuple[str, str]]:
    """Return a combo box's (text, data) pairs."""
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def check_with_raw(window) -> None:
    """Check the station combo of the survey whose raw folders are present."""
    state = window.state
    assert sorted(state.raw_sites()) == sorted(RAW_FOLDERS), state.raw_sites()
    items = combo_items(window.process_tab.station_combo)
    assert items == WITH_RAW, items
    lost = set(state.raw_sites()) - {name for _t, name in items}
    assert not lost, f"raw folders no longer listed: {lost}"


def check_stale(window) -> None:
    """Check the station combo, a queued run and the remote labels with data_root stale."""
    state, tab = window.state, window.process_tab
    assert state.raw_sites() == {}, state.raw_sites()
    items = combo_items(tab.station_combo)
    assert items == STALE, items
    tab.station_combo.setCurrentIndex(tab.station_combo.findData("S03"))
    remotes = dict((name, text) for text, name in combo_items(tab.remote_combo))
    assert remotes.get("S01") == "S01  (archive)" and remotes.get("STK_X") == "STK_X  (stack)", remotes
    tab.remote_combo.setCurrentIndex(tab.remote_combo.findData("S01"))
    assert tab.add_button.isEnabled(), tab.status_label.text()
    argv = tab.queue_process()
    assert argv is not None and argv[1].endswith("process_rr.py") and argv[3:5] == ["S03", "S01"], argv
    assert tab.runner.jobs[-1].label.startswith("process_rr S03 rr-S01"), tab.runner.jobs[-1].label


def check_ingest(survey_yaml: Path) -> None:
    """`ingest_site` keeps an archive whose raw folder is not found and names the folder when there is no archive."""
    from mt_workbench.ingest import ingest_site
    from mt_workbench.survey import Survey

    survey = Survey.from_yaml(survey_yaml)
    archive = survey.workspace / "mth5" / "S03.h5"
    before = archive.stat().st_mtime_ns, archive.stat().st_size
    assert ingest_site(survey, "S03") == archive
    assert (archive.stat().st_mtime_ns, archive.stat().st_size) == before, "S03's archive was touched"
    try:
        ingest_site(survey, "S04")
    except FileNotFoundError as exc:
        assert "no raw folder S04" in str(exc) and "no archive at" in str(exc), exc
    else:
        raise AssertionError("ingest_site S04 (no raw folder, no archive) did not raise")


def load_process_rr():
    """Import scripts/process_rr.py as a module."""
    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def decisions(rr, survey_yaml: Path, local: str, remote: str) -> dict:
    """Return what process_rr decides for a pair: virtual flag, archive read, status, filter records."""
    args = rr.build_parser().parse_args([str(survey_yaml), local, remote, "--dry-run"])
    res = rr.resolve(args, dt.datetime(2026, 10, 9, 7, 0, tzinfo=dt.timezone.utc))
    status = res["remote_status"]
    return {"virtual": res["virtual_remote"], "remote_archive": Path(res["remote_archive"]).name,
            "variant": None if status is None else (status["variant"] and Path(status["variant"]).name),
            "state": None if status is None else status["variant_state"],
            "filters_local": rr._declared_filters(res["survey"], local, res["raw_sites"]),
            "filters_remote": rr._declared_filters(res["survey"], remote, res["raw_sites"])}


def check_recorded_remotes(rr, survey_yaml: Path) -> str:
    """Check process_rr's decisions on recorded and virtual remotes under the three roots (workbench issue 32)."""
    import h5py

    from mt_workbench.ingest import variant_path
    from mt_workbench.survey import Survey

    config = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))
    for name in ("S01", "S03", "S01L", "S02L", "OBS"):  # spans from survey.yaml; the burst sites take their parents'
        config["sites"][name].update(SPAN)
    survey_yaml.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (survey_yaml.parent / "filters.yaml").write_text(yaml.safe_dump(FILTERS, sort_keys=False), encoding="utf-8")
    with h5py.File(Path(config["workspace"]) / "mth5" / "STK_X.h5", "w"):  # a stack's span is read from its archive
        pass
    root = survey_yaml.parent
    seen: dict[tuple, dict] = {}
    for data_root in (root / "raw", root / MOVED, root / UNMOUNTED):
        set_data_root(survey_yaml, data_root)
        survey = Survey.from_yaml(survey_yaml)
        for local, remote in RECORDED_PAIRS:
            got = decisions(rr, survey_yaml, local, remote)
            assert got["virtual"] is False, (data_root.name, local, remote, got)
            assert got["variant"] == variant_path(survey, remote).name, (data_root.name, local, remote, got)
            assert got["state"] and got["state"].startswith("to build"), (data_root.name, local, remote, got)
            assert got["filters_remote"] == FILTERS[remote] and got["filters_local"] == FILTERS[local], got
            assert seen.setdefault((local, remote), got) == got, (data_root.name, local, remote, got,
                                                                  seen[(local, remote)])
        for local, remote in VIRTUAL_PAIRS:
            got = decisions(rr, survey_yaml, local, remote)
            assert got["virtual"] is True and got["filters_remote"] is None, (data_root.name, local, remote, got)
            assert got["remote_archive"] == f"{remote}.h5", (data_root.name, local, remote, got)
            assert seen.setdefault((local, remote), got) == got, (data_root.name, local, remote, got)
    return (f"process_rr under {root.name}/raw, {MOVED} and {UNMOUNTED}: S03 rr S01 and S01 rr S03 not virtual, "
            f"variant named, filters recorded, the same under the three roots; "
            + ", ".join(f"{a} rr {b}" for a, b in VIRTUAL_PAIRS) + " virtual, no filter record")


def run(app, mutate: bool = False) -> list[str]:
    """Run the scratch-survey checks of the Process tab and `ingest_site`; return what was checked."""
    done = []
    survey_yaml = make_survey()
    window = MainWindow(survey_yaml=survey_yaml)
    pump(app)
    try:
        check_with_raw(window)
        done.append("raw folders present: " + ", ".join(t for t, _n in WITH_RAW))
        for stale in (MOVED, UNMOUNTED):
            set_data_root(survey_yaml, SCRATCH / "survey" / stale)
            window.open_survey(survey_yaml)
            pump(app)
            check_stale(window)
            done.append(f"data_root {stale}: " + ", ".join(t for t, _n in STALE) + "; S03 rr-S01 queued")
            if not mutate:
                check_ingest(survey_yaml)
                done.append(f"data_root {stale}: ingest_site keeps S03's archive, names S04's missing raw folder")
    finally:
        window.state.runner.reset()
        window.close()
        pump(app)
    return done


def atlas_raw_folders(data_root: Path) -> set[str]:
    """The Atlas raw site folders under `data_root`, found by their LEMI-423 files alone, or none when unreachable."""
    try:
        return {d.name for d in data_root.iterdir()
                if d.is_dir() and any(re.fullmatch(r"\d+\.B423", f.name) for f in d.iterdir())}
    except OSError:
        return set()


def atlas_expected(atlas_yaml: Path) -> tuple[list[str], set[str], dict] | None:
    """The Atlas station list from survey.yaml's text, its raw folders and the mth5 folder, or None when unreachable.

    Returns:
        tuple | None: (sorted station names, raw folder names, the sites block).
    """
    if not atlas_yaml.exists():
        return None
    config = yaml.safe_load(atlas_yaml.read_text(encoding="utf-8"))
    mth5 = Path(config["workspace"]) / "mth5"
    if not mth5.is_dir():
        return None
    sites = config.get("sites") or {}
    raw = atlas_raw_folders(Path(config["data_root"]))
    archived = {n for n, e in sites.items()
                if (mth5 / f"{n}.h5").exists() and (e or {}).get("instrument") != "intermagnet"}
    return sorted(raw | archived), raw, sites


def check_atlas(window, expected: list[str], raw: set[str], sites: dict) -> None:
    """Check the Atlas station combo against `expected`: raw folders plain, every other site labelled by its kind."""
    assert set(window.state.raw_sites()) == raw, sorted(set(window.state.raw_sites()) ^ raw)
    items = combo_items(window.process_tab.station_combo)
    names = [name for _t, name in items]
    assert names == expected, (len(names), len(expected), sorted(set(names) ^ set(expected)))
    for text, name in items:
        entry = sites.get(name) or {}
        if name in raw:
            assert text == name, text
        elif entry.get("derived_from"):
            assert text.startswith(f"{name}  (derived from {entry['derived_from']}, "), text
        elif entry.get("bursts_of"):
            assert text.startswith(f"{name}  (bursts of {entry['bursts_of']}, "), text
        else:
            assert text == f"{name}  (archive)", text
    for name in ("B30", "B31"):  # archives not declared since 27 Sep: listed only as raw folders
        assert name not in names or name in raw, name
    for name in ("EBR", "SPT"):  # observatories: remotes only
        assert name not in names, name


def main() -> int:
    """Run the checks, the mutations and the Atlas comparison; return 0 on success."""
    atlas_yaml = Path(sys.argv[sys.argv.index("--atlas") + 1]) if "--atlas" in sys.argv else ATLAS_YAML
    app = QApplication.instance() or QApplication(sys.argv)
    for line in run(app):
        print(f"  {line}")

    # the mutation: the station list built from the raw folders alone
    fixed = State.station_choices
    State.station_choices = lambda self: [(n, n) for n in sorted(self.raw_sites())]
    try:
        run(app, mutate=True)
    except AssertionError as exc:
        print(f"  mutation (raw folders alone) trips: {str(exc)[:100]}")
    else:
        raise AssertionError("the mutation (station list from raw_sites alone) did not trip the test")
    finally:
        State.station_choices = fixed

    rr = load_process_rr()
    print(f"  {check_recorded_remotes(rr, SCRATCH / 'survey' / 'survey.yaml')}")

    # the mutation: process_rr's raw sites as the folders found alone
    def folders_found(survey):
        try:
            return survey.site_dirs()
        except OSError:
            return {}

    fixed_folders = rr.recorded_site_folders
    rr.recorded_site_folders = folders_found
    try:
        check_recorded_remotes(rr, SCRATCH / "survey" / "survey.yaml")
    except AssertionError as exc:
        print(f"  mutation (process_rr's raw sites as the folders found) trips: {str(exc)[:100]}")
    else:
        raise AssertionError("the mutation (recorded_site_folders reduced to site_dirs) did not trip the test")
    finally:
        rr.recorded_site_folders = fixed_folders

    found = atlas_expected(atlas_yaml)
    if found is None:
        print(f"  Atlas survey {atlas_yaml} or its workspace not reachable: skipped")
    else:
        expected, raw, sites = found
        window = MainWindow(survey_yaml=atlas_yaml)
        pump(app)
        try:
            check_atlas(window, expected, raw, sites)
        finally:
            window.close()
            pump(app)
        print(f"  Atlas {atlas_yaml} (data_root {window.state.survey.data_root}, {len(raw)} raw folders): "
              f"{len(expected)} stations, as survey.yaml, the raw folders and mth5/ give them; "
              f"B30, B31 listed only as raw folders, EBR and SPT not listed")

    assert not SLOT_ERRORS, f"{len(SLOT_ERRORS)} Qt slot error(s)"
    print("\nPASS  process_station_list_unit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
