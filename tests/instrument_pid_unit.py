# -*- coding: utf-8 -*-
"""
Unit test of the instrument registry DOIs: survey.yaml keys, archives, sidecar, EDI, XML, merge and lookup

A survey declares the AuScope instrument registry DOIs of the instruments a
site used (`logger_pid`, `sensor_pid_hx`, `sensor_pid_hy`, `sensor_pid_hz`,
`electrode_pid`, and `platform_pid` at the top level or per site;
`mt_workbench.survey.SiteConfig`). Ingest writes them into the run and
station comments, scripts/process_rr.py into the sidecar's
`instrument_pids`, the EDI's INFO block and the XML's Notes, and
scripts/merge_best.py carries its base's and its sources'.
scripts/pidinst_lookup.py proposes them from the serials. Everything here
runs on scratch copies and synthetic files; the registry is read from the
saved response tests/fixtures/pidinst_search_10307.json (serial 10307, read
2026-11-08) instead of the network. The DOIs used are real registry DOIs
of that response (the Orange Box 10307 10.82388/25jrcc6q, the Phoenix MTU-5C
10307 10.82388/egmph7x7, the Kalkaroo 2020-21 platform 10.82388/k682rsrf)
and of instruments.csv of Kalgoorlie (box 2, 10.82388/a092l1jc); the roles
some of them play below (a coil, a platform of a synthetic survey) are the
test's own.

Usage:
    python tests/instrument_pid_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**
  - `SiteConfig` takes a URL ("https://doi.org/10.82388/25jrcc6q"), a
    "doi:" prefix, a box name ("hfm2"), a number or an empty string as a
    pid key without a ValueError whose message gives the form
    10.<prefix>/<suffix>; or it refuses a bare DOI or the word none (any
    case, stored "none"); or `Survey` takes a bad top-level `platform_pid`;
  - `Survey.instrument_pids` does not give, in order, a site's logger,
    sensors, electrode and platform (the site's `platform_pid` over the
    top-level one, `defaults:` keys applied), a site with `h_from` its
    neighbour's logger as `logger_hx_hy` and the neighbour's hx and hy
    sensor DOIs, a derived site its parent's, a burst site its recorded
    site's, or an empty dict for a site of a survey with no key;
  - the ingest of a synthetic Orange Box site with the keys does not write
    the line "instrument_registry: logger <doi>, platform <doi>" into every
    run comment and the station's provenance comment, or one without the
    keys writes "instrument_registry" anywhere;
  - `process_rr.build_sidecar`, on a scratch copy of curnamona_cube's
    survey.yaml with D02's logger and E08's logger and coils declared, does
    not give `instrument_pids` {local: {site D02, pids}, remote: {site E08,
    pids}}, or `edi_info_lines` not one line per instrument
    (mt_workbench.instrument_pid_local_logger=...), or a dry run of the copy
    does not print `instrument_pid.local` and `instrument_pid.remote`; or
    on the unchanged config the sidecar holds `instrument_pids`, the lines
    any instrument_pid line or the dry run any instrument_pid line; a stack
    remote's entry does not list its members' DOIs;
  - the EDI that `write_products` writes from a TF carrying those lines
    lacks them in its INFO block, they do not read back through
    `products.read_tf` to the same DOIs by role (the dotted-key loss of
    upstream 115 is why the keys are written with underscores), every INFO
    line is not under INFO_MAX, or the XML's Notes lack each DOI as an
    https://doi.org/ link; or a TF without the lines gets an instrument_pid
    line or a doi.org link;
  - `merge_best.merge_files` of two such EDIs (the base with remote logger
    A, a second source with remote logger B taking the yx row) does not keep
    the base's lines, add the second source's remote DOI as
    `instrument_pid_src2_remote_logger`, record both in the sidecar's
    `instrument_pids`, and name every DOI in the merged XML's Notes; or a
    merge of sources without the lines writes any;
  - the lookup helper, on the saved response, does not keep only the
    Orange Box for an Orange Box site (the MTU-5C with the same serial and
    the two platforms left out), find nothing for a LEMI-423 site, find the
    MTU-5C for a Phoenix site but refuse it because its commissioning (2020)
    is after the site's span (2006), call the serial ambiguous without a
    model filter, or its `--write` on a scratch survey.yaml does not add
    exactly the one key (parsed diff), keep the comment count and the CRLF
    line endings, and leave a dated copy; or an unreachable registry does
    not exit 1 with one line, writing nothing.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))
FIXTURE = REPO / "tests" / "fixtures" / "pidinst_search_10307.json"
CURNAMONA = REPO / "surveys" / "curnamona_cube"
BOX1 = "10.82388/25jrcc6q"  # Orange Box serial 10307 (inventory 1)
BOX2 = "10.82388/a092l1jc"  # Orange Box serial 51374 (inventory 2)
MTU = "10.82388/egmph7x7"  # Phoenix MTU-5C serial 10307
PLATFORM = "10.82388/k682rsrf"  # the Kalkaroo 2020-21 platform record


def _load(name: str, path: Path):
    """Import a script or test file as a module."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quiet(func, *args, **kwargs):
    """Call func with stdout and stderr captured; return (result, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        result = func(*args, **kwargs)
    return result, out.getvalue(), err.getvalue()


def test_keys_validated() -> None:
    from mt_workbench.survey import SiteConfig, Survey

    good = SiteConfig(name="S", logger_pid=BOX1, sensor_pid_hx=MTU, electrode_pid="None", platform_pid=" NONE ")
    assert (good.logger_pid, good.sensor_pid_hx, good.electrode_pid, good.platform_pid) == \
        (BOX1, MTU, "none", "none"), good
    for bad in (f"https://doi.org/{BOX1}", f"doi:{BOX1}", "hfm2", 10307, "", "10.82388", "10.8/x"):
        try:
            SiteConfig(name="S", logger_pid=bad)
        except ValueError as exc:
            assert "10.<prefix>/<suffix>" in str(exc), exc
        else:
            raise AssertionError(f"logger_pid {bad!r} accepted")
    try:
        Survey({"name": "t", "data_root": ".", "platform_pid": f"https://doi.org/{PLATFORM}"}, Path("."))
    except ValueError as exc:
        assert "10.<prefix>/<suffix>" in str(exc), exc
    else:
        raise AssertionError("a URL as the top-level platform_pid accepted")
    print(f"  keys: a bare DOI and none accepted; URL, doi:, box name, number, empty, no suffix refused")


def _pid_survey() -> "Survey":
    """Return an in-memory survey with every kind of site the pids are resolved for."""
    from mt_workbench.survey import Survey

    config = {
        "name": "pidtest", "instrument": "orangebox", "data_root": str(Path(tempfile.gettempdir()) / "no_such_root"),
        "sample_rate": 10, "platform_pid": PLATFORM,
        "defaults": {"electrode_pid": "none", "electric_full_scale_uv": 25000.0, "magnetic_full_scale_nt": 70000.0},
        "sites": {
            "A": {"logger_pid": BOX1, "sensor_pid_hz": MTU},
            "B": {"logger_pid": BOX2, "sensor_pid_hx": MTU, "sensor_pid_hy": BOX1, "platform_pid": BOX2},
            "C": {"logger_pid": BOX1, "h_from": "B"},
            "AL": {"derived_from": "A", "sample_rate": 1.0},
            "N": {},
        },
    }
    return Survey(config, Path(tempfile.gettempdir()))


def test_survey_instrument_pids() -> None:
    from mt_workbench.survey import Survey

    survey = _pid_survey()
    got = survey.instrument_pids("A")
    assert list(got.items()) == [("logger", BOX1), ("sensor_hz", MTU), ("electrode", "none"),
                                 ("platform", PLATFORM)], got
    b = survey.instrument_pids("B")
    assert list(b.items()) == [("logger", BOX2), ("sensor_hx", MTU), ("sensor_hy", BOX1), ("electrode", "none"),
                               ("platform", BOX2)], b
    c = survey.instrument_pids("C")
    assert list(c.items()) == [("logger", BOX1), ("logger_hx_hy", BOX2), ("sensor_hx", MTU), ("sensor_hy", BOX1),
                               ("electrode", "none"), ("platform", PLATFORM)], c
    assert survey.instrument_pids("AL") == got, survey.instrument_pids("AL")
    assert list(survey.instrument_pids("N").items()) == [("electrode", "none"), ("platform", PLATFORM)]
    note = survey.registry_note("A")
    assert note == f"instrument_registry: logger {BOX1}, sensor_hz {MTU}, electrode none, platform {PLATFORM}", note
    assert ";" not in note and note.split(":", 1)[0] == "instrument_registry", note
    bare = Survey({"name": "t", "data_root": ".", "sites": {"X": {"serial": "10307"}}}, Path("."))
    assert bare.instrument_pids("X") == {} and bare.registry_note("X") is None
    burst = Survey({"name": "t", "instrument": "phoenix", "data_root": ".", "sites": {
        "P": {"logger_pid": MTU, "calibration_dir": "."},
        "PH": {"bursts_of": "P", "sample_rate": 24000}}}, Path("."))
    assert burst.instrument_pids("PH") == {"logger": MTU}, burst.instrument_pids("PH")
    print(f"  instrument_pids: A {got}; C (h_from B) {c}; derived AL = A; burst PH = P; no key -> {{}}")
    print(f"  registry_note A: {note}")


def test_ingest_comments() -> None:
    from mt_workbench.ingest import ingest_site
    from mt_workbench.survey import Survey
    from mth5.mth5 import MTH5

    hf = _load("orangebox_h_from_unit", REPO / "tests" / "orangebox_h_from_unit.py")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        hf._write_site(root / "raw" / "S1", hf.T0, {"hx": 300.0, "hy": 410.0}, 1)
        hf._write_site(root / "raw" / "L1", hf.T0, {"hx": 777.0, "hy": 133.0}, 2)
        found = {}
        for name, s1, top in (("keys", {"logger_pid": BOX1}, {"platform_pid": PLATFORM}), ("plain", {}, {})):
            path = hf._survey(root, name, s1)
            config = yaml.safe_load(path.read_text(encoding="utf-8"))
            config.update(top)
            path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            out = ingest_site(Survey.from_yaml(path), "S1", overwrite=True)
            m = MTH5()
            m.open_mth5(out, mode="r")
            try:
                station = m.get_station("S1", survey="obhfrom")
                runs = [str(station.get_run(r).metadata.comments.value or "") for r in station.groups_list
                        if r.startswith("sr")]
                found[name] = (runs, str(station.metadata.provenance.comments.value or ""))
            finally:
                m.close_mth5()
    line = f"instrument_registry: logger {BOX1}, platform {PLATFORM}"
    runs, station = found["keys"]
    assert runs and all(line in r for r in runs), runs
    assert line in station, station
    runs, station = found["plain"]
    assert not any("instrument_registry" in r for r in runs) and "instrument_registry" not in station
    print(f"  ingest: {len(found['keys'][0])} run comment(s) and the station comment hold {line!r}; "
          f"none without the keys")


def _curnamona_copy(scratch: Path, sites: dict | None) -> Path:
    """Write a scratch copy of curnamona_cube's config, with pid keys added to the named sites."""
    for name in ("survey.yaml", "filters.yaml"):
        if (CURNAMONA / name).exists():
            (scratch / name).write_bytes((CURNAMONA / name).read_bytes())
    path = scratch / "survey.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["workspace"] = str(CURNAMONA / "work")
    for site, keys in (sites or {}).items():
        config["sites"].setdefault(site, {}).update(keys)
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _sidecar(process_rr, survey_yaml: Path) -> tuple[dict, list[str]]:
    """Resolve D02 rr E08 on a config and build its sidecar and INFO lines with a fake TF."""
    import numpy as np

    prr_unit = _load("process_rr_cli_unit", REPO / "tests" / "process_rr_cli_unit.py")
    started = dt.datetime(2026, 11, 8, 11, 0, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    args = process_rr.build_parser().parse_args([str(survey_yaml), "D02", "E08", "--tag", "pid"])
    res = process_rr.resolve(args, started)
    edi = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
    quadrant = process_rr.phase_quadrants(prr_unit._fake_tf(45.0, -135.0, np.geomspace(0.1, 10.0, 8)))
    sidecar = process_rr.build_sidecar(res, args, started, started, edi, edi.with_suffix(".png"), quadrant, [])
    return sidecar, process_rr.edi_info_lines(sidecar)


def _dry_run(survey_yaml: Path) -> list[str]:
    """Return the instrument_pid lines of a dry run of D02 rr E08 on a config."""
    done = subprocess.run([sys.executable, str(REPO / "scripts" / "process_rr.py"), str(survey_yaml), "D02", "E08",
                           "--dry-run"], capture_output=True, text=True, cwd=REPO)
    assert done.returncode == 0, done.stderr[-2000:]
    return [line for line in done.stdout.splitlines() if "instrument_pid" in line]


def test_sidecar_and_info_lines() -> None:
    process_rr = _load("process_rr", REPO / "scripts" / "process_rr.py")
    with tempfile.TemporaryDirectory() as tmp:
        keyed = _curnamona_copy(Path(tmp), {"D02": {"logger_pid": BOX1},
                                            "E08": {"logger_pid": MTU, "sensor_pid_hx": BOX2}})
        sidecar, lines = _sidecar(process_rr, keyed)
        dry = _dry_run(keyed)
        plain_dir = Path(tmp) / "plain"
        plain_dir.mkdir()
        plain = _curnamona_copy(plain_dir, None)
        plain_side, plain_lines = _sidecar(process_rr, plain)
        plain_dry = _dry_run(plain)
        stack = process_rr.instrument_pids_of(process_rr.Survey.from_yaml(keyed), "STK_test", members=["D02", "E08"])
    want = {"local": {"site": "D02", "pids": {"logger": BOX1}},
            "remote": {"site": "E08", "pids": {"logger": MTU, "sensor_hx": BOX2}}}
    assert sidecar.get("instrument_pids") == want, sidecar.get("instrument_pids")
    pid_lines = [line for line in lines if "instrument_pid" in line]
    assert pid_lines == [f"mt_workbench.instrument_pid_local_logger={BOX1}",
                         f"mt_workbench.instrument_pid_remote_logger={MTU}",
                         f"mt_workbench.instrument_pid_remote_sensor_hx={BOX2}"], pid_lines
    assert dry == [f"instrument_pid.local: D02 logger {BOX1}",
                   f"instrument_pid.remote: E08 logger {MTU}, sensor_hx {BOX2}"], dry
    assert "instrument_pids" not in plain_side, plain_side.get("instrument_pids")
    assert not [line for line in plain_lines if "instrument_pid" in line] and not plain_dry, (plain_lines, plain_dry)
    assert stack == {"site": "STK_test", "members": {"D02": {"logger": BOX1},
                                                     "E08": {"logger": MTU, "sensor_hx": BOX2}}}, stack
    print(f"  sidecar instrument_pids: {sidecar['instrument_pids']}")
    print(f"  INFO lines: {pid_lines}")
    print(f"  dry run: {dry}; unchanged config: no key, no line; stack entry {stack}")


def _tf_with_lines(lines: list[str]):
    """Return the aurora-shaped TF of process_rr_cli_unit with these processing parameters."""
    prr_unit = _load("process_rr_cli_unit", REPO / "tests" / "process_rr_cli_unit.py")
    tf = prr_unit._aurora_like_tf()
    z = tf.impedance.data.copy()
    z[:, 0, 0], z[:, 1, 1] = 0.1 + 0.1j, -0.1 - 0.1j  # merge_best takes a row only where both its values are nonzero
    tf.impedance = z
    tf.station_metadata.transfer_function.processing_parameters = list(lines)
    return tf


def test_products_carry_pids() -> None:
    from mt_workbench.products import INFO_MAX, INFO_PREFIX, read_tf, tf_instrument_pids, write_products

    lines = [f"mt_workbench.instrument_pid_local_logger={BOX1}", f"mt_workbench.instrument_pid_remote_logger={BOX2}",
             f"mt_workbench.instrument_pid_remote_m1_sensor_hx={MTU} (Kal014)"]
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_products(_tf_with_lines(lines), Path(tmp) / "FAKE_rr-REM_20261108-1100_pid.edi")
        edi = paths["edi"].read_text(encoding="latin-1")
        xml = paths["xml"].read_text(encoding="utf-8")
        back = tf_instrument_pids(read_tf(paths["edi"]))
        control = write_products(_tf_with_lines([]), Path(tmp) / "control.edi")
        cedi, cxml = control["edi"].read_text(encoding="latin-1"), control["xml"].read_text(encoding="utf-8")
    for line in lines:
        assert line in edi, line
        assert len(INFO_PREFIX + line) < INFO_MAX, line
    # read back from the EDI, the keys come in lower case (the member's site is in the value for that reason)
    assert back == {"local_logger": BOX1, "remote_logger": BOX2, "remote_m1_sensor_hx": f"{MTU} (Kal014)"}, back
    notes = re.search(r"<Notes>(.*?)</Notes>", xml, re.S)
    assert notes, "no Notes"
    for doi in (BOX1, BOX2, MTU):
        assert f"https://doi.org/{doi}" in notes.group(1), (doi, notes.group(1))
    assert f"remote stack member Kal014 sensor hx https://doi.org/{MTU}" in notes.group(1), notes.group(1)
    assert "instrument_pid" not in cedi and "doi.org" not in cxml, "control carries a pid"
    sentence = notes.group(1)[notes.group(1).find("Instruments"):].strip()
    print(f"  EDI INFO holds the 3 lines; read back {back}")
    print(f"  XML Notes: {sentence[:300]}")


def test_merge_carries_pids() -> None:
    import merge_best
    from mt_workbench.products import write_products

    base_lines = [f"mt_workbench.instrument_pid_local_logger={BOX1}", f"mt_workbench.instrument_pid_remote_logger={BOX2}"]
    other_lines = [f"mt_workbench.instrument_pid_local_logger={BOX1}", f"mt_workbench.instrument_pid_remote_logger={MTU}"]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        a = write_products(_tf_with_lines(base_lines), tmp / "FAKE_rr-A_20261108-1100_a.edi")["edi"]
        b = write_products(_tf_with_lines(other_lines), tmp / "FAKE_rr-B_20261108-1100_b.edi")["edi"]
        recipe = {"xy": [{"edi": str(a), "pmin": 0.001, "pmax": 1000.0}],
                  "yx": [{"edi": str(b), "pmin": 0.001, "pmax": 1000.0}]}
        status, _out, err = _quiet(merge_best.merge_files, tmp / "FAKE_best.edi", recipe, tag="pid", argv=["test"])
        assert status == 0, err
        edi = (tmp / "FAKE_best.edi").read_text(encoding="latin-1")
        xml = (tmp / "FAKE_best.xml").read_text(encoding="utf-8")
        side = json.loads((tmp / "FAKE_best.json").read_text(encoding="utf-8"))
        c = write_products(_tf_with_lines([]), tmp / "FAKE_rr-C_20261108-1100_c.edi")["edi"]
        plain = {"xy": [{"edi": str(c), "pmin": 0.001, "pmax": 1000.0}],
                 "yx": [{"edi": str(c), "pmin": 0.001, "pmax": 1000.0}]}
        status, _out, err = _quiet(merge_best.merge_files, tmp / "PLAIN_best.edi", plain, argv=["test"])
        assert status == 0, err
        pedi = (tmp / "PLAIN_best.edi").read_text(encoding="latin-1")
        pside = json.loads((tmp / "PLAIN_best.json").read_text(encoding="utf-8"))
    for line in base_lines + [f"mt_workbench.instrument_pid_src2_remote_logger={MTU}"]:
        assert line in edi, line
    assert "instrument_pid_src2_local_logger" not in edi, "the second source's local DOI equals the base's"
    assert side.get("instrument_pids") == {
        "base": {"edi": a.name, "pids": {"local_logger": BOX1, "remote_logger": BOX2}},
        "sources": {"2": {"edi": b.name, "pids": {"remote_logger": MTU}}}}, side.get("instrument_pids")
    notes = re.search(r"<Notes>(.*?)</Notes>", xml, re.S).group(1)
    for doi in (BOX1, BOX2, MTU):
        assert f"https://doi.org/{doi}" in notes, (doi, notes)
    assert "instrument_pid" not in pedi and "instrument_pids" not in pside, "a merge without pids wrote some"
    print(f"  merge: base lines kept, src2_remote_logger {MTU} added; sidecar {side['instrument_pids']}")


def test_lookup_helper() -> None:
    import pidinst_lookup as lk

    response = json.loads(FIXTURE.read_text(encoding="utf-8"))
    box = lk.candidates(response, "10307", lk.MODEL_TOKENS["orangebox"])
    assert [c["doi"] for c in box] == [BOX1], box
    assert lk.candidates(response, "10307", lk.MODEL_TOKENS["lemi423"]) == []
    mtu = lk.candidates(response, "10307", lk.MODEL_TOKENS["phoenix"])
    assert [c["doi"] for c in mtu] == [MTU], mtu
    assert lk.dates_cover(mtu[0], "2006-05-02T06:56:00Z", "2006-05-04T00:40:03Z") is False
    assert lk.dates_cover(box[0], "2006-05-02T06:56:00Z", "2006-05-04T00:40:03Z") is True
    assert len(lk.candidates(response, "10307", None)) == 2, "no model filter: the serial is ambiguous"

    text = ("name: looktest\ninstrument: orangebox\ndata_root: D:/no_such_root\n"
            "# the sites block below is hand kept\nsites:\n"
            "  S1:\n    serial: '10307'\n    start: '2006-05-02T06:56:00Z'\n    end: '2006-05-04T00:40:03Z'\n"
            "    # a comment inside the entry\n    notes: box 1\n"
            "  S2:\n    instrument: phoenix\n    serial: '10307'\n    start: '2006-05-02T06:56:00Z'\n"
            "  S3:\n    instrument: lemi423\n    serial: '10307'\n"
            "  S4:\n    serial: '10307'\n    logger_pid: none\n").replace("\n", "\r\n")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        responses = tmp / "responses"
        responses.mkdir()
        shutil.copy2(FIXTURE, responses / "10307.json")
        path = tmp / "survey.yaml"
        path.write_bytes(text.encode("utf-8"))
        status, out, err = _quiet(lk.main, [str(path), "--responses", str(responses), "--write"])
        assert status == 0, err
        new = path.read_bytes().decode("utf-8")
        copies = sorted(p.name for p in tmp.glob("survey.yaml.before_pidinst_*"))
        diff = lk.parsed_diff(text, new)
        lk.API = "http://127.0.0.1:9/api/3/action/package_search"  # nothing listens on the discard port
        before = path.read_bytes()
        fail, fout, ferr = _quiet(lk.main, [str(path), "--site", "S2"])
        unchanged = path.read_bytes() == before
    assert diff == {"added": {"S1": {"logger_pid": BOX1}}, "other": []}, diff
    assert lk.comment_lines(new) == lk.comment_lines(text) == 2, (lk.comment_lines(text), lk.comment_lines(new))
    assert new.count("\r\n") == text.count("\r\n") + 1 and "\n" not in new.replace("\r\n", ""), "line endings"
    assert "    serial: '10307'\r\n    logger_pid: '10.82388/25jrcc6q'\r\n" in new, new
    assert len(copies) == 1, copies
    assert "EXCLUDE" in out and "no record" in out, out
    assert fail == 1 and unchanged and ferr.count("\n") == 1 and ferr.startswith("ERROR registry not reached"), \
        (fail, ferr)
    print(f"  lookup: S1 Orange Box -> {BOX1} written (copy {copies[0]}); S2 MTU-5C refused by dates; S3 no "
          f"record; S4 declared none, not searched; unreachable registry: exit {fail}, {ferr.strip()[:80]}")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  instrument_pid_unit ({len(tests)} tests)")
