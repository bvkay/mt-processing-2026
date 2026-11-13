# -*- coding: utf-8 -*-
"""
Unit test for scripts/diagonal_site.py (the diagonal electric field of a shared-centre site)

Two synthetic EDL sites at 10 Hz are written as hourly ASCII files and
ingested with `ingest_site`, so their archives carry mt-io's real EDL chain
(the signed dipole stage, the x10 terminal box). Each holds a known
electric field E = (E_n, E_e) in mV/km and a common voltage V(t) of 1e5
words on both lines (the shared centre's), in the logger's words:
ex = round(10 g_x E.u(0)) + round(V), ey = round(10 g_y E.u(90)) + round(V),
g the signed dipole gain of mt-io's convention (-L for a line laid along
its channel's azimuth, +L for one laid the other way):

- S: lines 48 m at 0 deg and 44 m at 90 deg (unequal arms);
- W: lines 50 m at 0 deg and 46 m at 270 deg (ey laid to the west);
- G: lines 50 m at 0/90 deg in two runs (hours 0 and 2), for the two-run diagonal.

Usage:
    python tests/diagonal_site_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

This test fails if:
  - `diagonal_geometry` does not give L_d = sqrt(Lx^2 + Ly^2) and theta_d =
    atan2(-s Ly, Lx) for the standard layout (equal arms 315 deg, 48/44 m
    317.49 deg, s = -1 42.51 deg), 45 deg for 0/270 and 225 deg for 180/90 with
    s = +1 (to 1e-9), or `archive_geometry` from the signed gains differs;
  - `check_chains` passes S's own ex and ey chains with anything but the
    dipole at stage 1, or does not refuse ey's terminal box at gain 1, an
    extra stage on ey, or an ey chain with no dipole stage;
  - the script on S does not exit 0, or the derived ex differs from
    ex - ey of the source anywhere (the common voltage must cancel exactly,
    the words being integers), or hx, hy, hz differ from the source's;
  - the derived ex calibrated through its chain (`load_station`) differs
    from E.u(theta_d) by more than one word (1 / (10 L_d) mV/km), at S
    (317.49 deg) and at W (42.61 deg): the sign convention end to end;
  - the archive's ex metadata does not state L_d and theta_d, or its run
    comment lacks "derived_by: diagonal_site", s, L_d and theta_d;
  - survey.yaml does not gain exactly the entry SD (parsed: every other
    site and top-level key equal; comment count equal; the old text a byte
    prefix of the new), or `Survey` does not read SD as derived from S with
    channels [ex, hx, hy, hz] at 10 Hz, L_d and theta_d;
  - a second run does not keep the archive and leave survey.yaml byte for
    byte; a run with --sign -1 does not rebuild it (cut with s 1) and
    change the entry in place, every other line unchanged;
  - process_rr.py --dry-run of SD against W does not print the output
    channels "ex, hz", or a real process_rr.py run of SD rr W (to 1,000 s)
    does not exit 0 and write an EDI whose ZYX and ZYY (values and
    variances) are EMPTY (1e32) at every period while ZXX and ZXY are
    estimated, whose EMEAS line for ex states AZM theta_d with the
    electrode coordinates X, Y = (0, s Ly) and X2, Y2 = (Lx, 0), and whose
    tipper is written, or whose sidecar's quadrant verdict is not "not
    judged" naming the diagonal (a diagonal row has no fixed quadrant);
  - the two-run diagonal GD rr W does not exit 0 with its XML and h5
    written and the XML read back (mt_metadata's empty ey in the first run
    only stopped the XML writer at TAS227LPD), or, with
    `_drop_unrecorded_lines` disabled, the XML write of the same estimate
    does not fail (the control);
  - `mt_workbench.process._one_electric_line` patches anything for
    outputs [ex, ey, hz], or does not restore aurora's two methods on exit
    for [ex, hz].

Mutation: with the derived ex written as ex + ey (s applied with the wrong
sign), the cancellation criterion trips (the derived ex holds 2 V).
"""

from __future__ import annotations

import copy
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml
from scipy import signal

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "scripts"))

import diagonal_site as ds  # noqa: E402
from _scratch import scratch_dir  # noqa: E402
from mt_workbench.ingest import default_archive_path, ingest_site  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402

SCRIPT = REPO / "scripts" / "diagonal_site.py"
PROCESS_RR = REPO / "scripts" / "process_rr.py"
SCRATCH = scratch_dir("diagonal_site_unit")
FS = 10.0
T0 = pd.Timestamp("2016-02-01T00:00:00", tz="UTC")
HOURS = 3
N = int(HOURS * 3600 * FS)
SITES = {"S": (48.0, 0.0, 44.0, 90.0), "W": (50.0, 0.0, 46.0, 270.0), "G": (50.0, 0.0, 50.0, 90.0)}  # Lx, az_x, Ly, az_y
FILE_HOURS = {"S": (0, 1, 2), "W": (0, 1, 2), "G": (0, 2)}  # G: two runs, the hour between them missing
HEADER = ("name: t\ninstrument: edl\nsample_rate: 10\n# a comment line\ndata_root: {raw}\nworkspace: {work}\n"
          "defaults:\n  channels: [ex, ey, hx, hy, hz]\n  sensor_type: bartington\n  flip_reversed_dipoles: true\n"
          "  # a comment inside defaults\nsites:\n")


def red(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return unit-variance red noise (integrated white noise, high-passed at 2000 s)."""
    x = np.cumsum(rng.standard_normal(n))
    x = signal.sosfiltfilt(signal.butter(2, (1 / 2000.0) / (FS / 2), "high", output="sos"), x)
    return x / x.std()


def write_site(root: Path, name: str, seed: int) -> dict:
    """Write one EDL site; return its field, common voltage and words."""
    lx, ax, ly, ay = SITES[name]
    rng = np.random.default_rng(seed)
    e_n, e_e, v = 2.0 * red(rng, N), 1.5 * red(rng, N), np.round(1e5 * red(rng, N))
    gx = -lx if ax == 0.0 else lx  # mt-io's signed dipole gain: -L along the channel's azimuth
    gy = -ly if ay == 90.0 else ly
    words = {"BX": np.round(2.8e6 + 2e4 * red(rng, N)), "BY": np.round(2e4 * red(rng, N)),
             "BZ": np.round(-3.3e6 + 50 * rng.standard_normal(N)),
             "EX": np.round(10 * gx * e_n) + v, "EY": np.round(10 * gy * e_e) + v}
    site = root / "raw" / name
    shutil.rmtree(site, ignore_errors=True)
    (site / "config").mkdir(parents=True)
    (site / "config" / "recorder.ini").write_text(
        "[recorder]\n" + "".join(f"channel_{k}_samplerate=10\n" for k in range(5)), encoding="utf-8")
    per = int(3600 * FS)
    for h in FILE_HOURS[name]:
        when = T0 + pd.Timedelta(hours=h)
        for suffix, values in words.items():
            np.savetxt(site / f"{name}_{when:%y%m%d%H%M%S}.{suffix}", values[h * per:(h + 1) * per].astype("int64"),
                       fmt="%d")
    return dict(e_n=e_n, e_e=e_e, v=v, words=words)


def build(root: Path) -> tuple[Path, dict]:
    """Write survey.yaml and the two sites, ingest them; return the yaml path and the truths."""
    root.mkdir(parents=True, exist_ok=True)
    text = HEADER.format(raw=(root / "raw").as_posix(), work=(root / "work").as_posix())
    for k, (name, (lx, ax, ly, ay)) in enumerate(SITES.items()):
        text += (f"  {name}:\n    dipole_length_ex: {lx}\n    dipole_length_ey: {ly}\n    azimuth_ex: {ax}\n"
                 f"    azimuth_ey: {ay}\n    latitude: -41.0\n    longitude: {146.0 + 0.01 * k}\n    elevation: 10.0\n"
                 f"    declination: 13.5\n    start: '2016-02-01T00:00:00Z'\n    end: '2016-02-01T03:00:00Z'\n")
        if name == "S":
            text += "    # a comment inside an entry\n"
    path = root / "survey.yaml"
    path.write_bytes(text.encode("utf-8"))
    sv = Survey.from_yaml(path)
    truths = {}
    for k, name in enumerate(SITES):
        truths[name] = write_site(root, name, 10 + k)
        ingest_site(sv, name, out_path=default_archive_path(sv, name), overwrite=True)
    return path, truths


def test_geometry() -> None:
    """L_d and theta_d of the standard, unequal, s = -1 and reversed layouts; the archive form agrees."""
    cases = [((50, 0, 50, 90, 1), 315.0), ((48, 0, 44, 90, 1), math.degrees(math.atan2(-44, 48)) % 360),
             ((48, 0, 44, 90, -1), math.degrees(math.atan2(44, 48))), ((50, 0, 50, 270, 1), 45.0),
             ((50, 180, 50, 90, 1), 225.0)]
    for (lx, ax, ly, ay, s), want in cases:
        geo = ds.diagonal_geometry(lx, ax, ly, ay, s)
        assert abs(geo["length"] - math.hypot(lx, ly)) < 1e-9, geo
        assert abs((geo["azimuth"] - want + 180) % 360 - 180) < 1e-9, (lx, ax, ly, ay, s, geo, want)
        gx = -lx if ax == 0 else lx
        gy = -ly if ay == 90 else ly
        arch = ds.archive_geometry(gx, 0.0, gy, 90.0, s)
        assert abs(arch["length"] - geo["length"]) < 1e-9 and abs(arch["azimuth"] - geo["azimuth"]) < 1e-9, (arch, geo)
        print(f"  {lx:g}/{ly:g} m at {ax:g}/{ay:g}, s {s:+d}: L_d {geo['length']:.4f} m, theta_d {geo['azimuth']:.4f} "
              f"deg (wanted {want % 360:.4f}); the archive form agrees")


def test_chains(path: Path) -> None:
    """check_chains passes S's chains and refuses the three altered ones."""
    from mth5.mth5 import MTH5

    sv = Survey.from_yaml(path)
    m = MTH5()
    m.open_mth5(default_archive_path(sv, "S"), mode="r")
    try:
        run = m.get_station("S", survey=m.surveys_group.groups_list[0]).get_run("sr10_0001")
        rx, ry = run.get_channel("ex").channel_response, run.get_channel("ey").channel_response
    finally:
        m.close_mth5()
    assert ds.check_chains(rx, ry) == 0, [f.name for f in rx.filters_list]
    box = copy.deepcopy(ry)
    box.filters_list[1].gain = 1.0
    extra = copy.deepcopy(ry)
    extra.filters_list = list(extra.filters_list) + [copy.deepcopy(extra.filters_list[1])]
    unnamed = copy.deepcopy(ry)
    unnamed.filters_list[0].name = "uoa_line_ey_44.0m"  # no stage of ey is a dipole stage any more
    for label, altered in (("terminal box at gain 1", box), ("an extra stage", extra), ("no dipole stage", unnamed)):
        try:
            ds.check_chains(rx, altered)
        except ValueError as exc:
            print(f"  refused ({label}): {str(exc)[:110]}")
        else:
            raise AssertionError(f"check_chains accepted ey with {label}")


def derived_samples(path: Path, name: str) -> dict:
    """Return each channel of a derived archive's first run, and the ex metadata and run comment."""
    from mth5.mth5 import MTH5

    m = MTH5()
    m.open_mth5(path, mode="r")
    try:
        run = m.get_station(name, survey=m.surveys_group.groups_list[0]).get_run("sr10_0001")
        out = {c: np.asarray(run.get_channel(c).hdf5_dataset[()], "float64") for c in run.groups_list}
        md = run.get_channel("ex").metadata
        out["meta"] = dict(length=float(md.dipole_length), azimuth=float(md.measurement_azimuth),
                           filters=[f.name for f in md.filters])
        out["comment"] = str(run.metadata.comments.value if hasattr(run.metadata.comments, "value")
                             else run.metadata.comments)
        return out
    finally:
        m.close_mth5()


def cancellation(got: dict, truth: dict) -> float:
    """Return the largest |derived ex - (ex - ey) of the words without V|; 0 when V cancels exactly."""
    w = truth["words"]
    want = (w["EX"] - truth["v"]) - (w["EY"] - truth["v"])
    return float(np.max(np.abs(got["ex"] - want)))


def run_script(path: Path, *extra: str) -> str:
    """Run diagonal_site.py on S; return its output, failing on a non-zero exit."""
    run = subprocess.run([sys.executable, str(SCRIPT), str(path), *extra], capture_output=True, text=True,
                         timeout=900)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text[-3000:]
    return text


def calibrated_error(path: Path, name: str, truth: dict, azimuth: float) -> tuple[float, float]:
    """Return the largest |calibrated derived ex - E.u(theta_d)| in mV/km and the one-word bound."""
    from mt_workbench.timefreq import load_station

    sv = Survey.from_yaml(path)
    rec = load_station(default_archive_path(sv, name), "t", name, comps=("ex",))
    cal = rec.value("ex")
    a = math.radians(azimuth)
    want = math.cos(a) * truth["e_n"] + math.sin(a) * truth["e_e"]
    n = min(cal.size, want.size)
    return float(np.max(np.abs(cal[:n] - want[:n]))), 1.0 / abs(rec.gains["ex"])


def test_script(path: Path, truths: dict) -> None:
    """The script on S and W: the archive, the calibration, the survey.yaml edit, the reruns and the mutation."""
    before = path.read_bytes()
    text = run_script(path, "S")
    after = path.read_bytes()
    sv = Survey.from_yaml(path)
    got = derived_samples(default_archive_path(sv, "SD"), "SD")
    worst = cancellation(got, truths["S"])
    assert worst <= 1e-9, worst
    for c, suffix in (("hx", "BX"), ("hy", "BY"), ("hz", "BZ")):
        assert np.array_equal(got[c], truths["S"]["words"][suffix]), c
    geo = ds.diagonal_geometry(48.0, 0.0, 44.0, 90.0, 1)
    assert abs(got["meta"]["length"] - geo["length"]) < 1e-9 and abs(got["meta"]["azimuth"] - geo["azimuth"]) < 1e-9, \
        got["meta"]
    for piece in ("derived_by: diagonal_site", "s +1", f"L_d {geo['length']:.4f} m", f"theta_d {geo['azimuth']:.4f} deg"):
        assert piece in got["comment"], (piece, got["comment"][:300])
    err, bound = calibrated_error(path, "SD", truths["S"], geo["azimuth"])
    assert err <= 1.01 * bound, (err, bound)
    print(f"  S: derived ex == ex - ey exactly (max |diff| {worst:g} words: V cancelled); hx hy hz copied; "
          f"L_d {geo['length']:.4f} m, theta_d {geo['azimuth']:.4f} deg in the metadata and the run comment; "
          f"calibrated vs E.u(theta_d) {err:.2e} mV/km (one word {bound:.2e})")
    # survey.yaml: the one entry added, parsed and by text
    old, new = yaml.safe_load(before), yaml.safe_load(after)
    assert after.startswith(before), "the old survey.yaml is not a byte prefix of the new"
    assert {k: v for k, v in old.items() if k != "sites"} == {k: v for k, v in new.items() if k != "sites"}
    assert list(new["sites"]) == list(old["sites"]) + ["SD"], list(new["sites"])
    assert all(new["sites"][k] == v for k, v in old["sites"].items())
    assert ds.comment_count(before.decode()) == ds.comment_count(after.decode()) == 3
    cfg = sv.site("SD")
    assert sv.parent_of("SD") == "S" and [c.lower() for c in cfg.channels] == ["ex", "hx", "hy", "hz"], cfg
    assert sv.sample_rate_of("SD") == 10.0 and abs(cfg.azimuth_ex - round(geo["azimuth"], 3)) < 1e-9 and \
        abs(cfg.dipole_length_ex - round(geo["length"], 3)) < 1e-9, cfg
    print(f"  survey.yaml: SD added ({len(before.splitlines())} -> {len(after.splitlines())} lines, comments 3 -> 3, "
          f"the old text a byte prefix); Survey reads SD from S, channels {cfg.channels}, {sv.sample_rate_of('SD'):g} Hz")
    # a second run keeps everything
    text = run_script(path, "S")
    assert "kept" in text and path.read_bytes() == after, text[-800:]
    # --sign -1 rebuilds and edits the entry in place
    text = run_script(path, "S", "--sign", "-1")
    assert "cut with s 1" in text, text[-800:]
    flipped = path.read_bytes()
    geo_m = ds.diagonal_geometry(48.0, 0.0, 44.0, 90.0, -1)
    sv = Survey.from_yaml(path)
    assert abs(sv.site("SD").azimuth_ex - round(geo_m["azimuth"], 3)) < 1e-9, sv.site("SD").azimuth_ex
    a_lines, b_lines = after.decode().splitlines(), flipped.decode().splitlines()
    head = a_lines.index("  SD:")
    assert a_lines[:head] == b_lines[:head] and len(a_lines) == len(b_lines), "lines outside SD changed"
    print(f"  rerun kept the archive and survey.yaml; --sign -1 rebuilt it (theta_d {geo_m['azimuth']:.2f} deg), the "
          f"entry changed in place, every line before it unchanged")
    run_script(path, "S", "--sign", "1")
    # W: ey laid to the west, the azimuth through the real chain
    run_script(path, "W")
    sv = Survey.from_yaml(path)
    geo_w = ds.diagonal_geometry(50.0, 0.0, 46.0, 270.0, 1)
    got_w = derived_samples(default_archive_path(sv, "WD"), "WD")
    assert cancellation(got_w, truths["W"]) <= 1e-9
    err_w, bound_w = calibrated_error(path, "WD", truths["W"], geo_w["azimuth"])
    assert err_w <= 1.01 * bound_w and abs(got_w["meta"]["azimuth"] - geo_w["azimuth"]) < 1e-9, (err_w, got_w["meta"])
    print(f"  W (ey at 270): theta_d {geo_w['azimuth']:.4f} deg; calibrated vs E.u(theta_d) {err_w:.2e} mV/km")
    # process_rr resolves SD's outputs as ex and hz
    run = subprocess.run([sys.executable, str(PROCESS_RR), str(path), "SD", "W", "--dry-run"], capture_output=True,
                         text=True, timeout=600)
    text = run.stdout + run.stderr
    assert run.returncode == 0 and "output_channels: ex, hz" in text, text[-2000:]
    print("  process_rr.py --dry-run SD rr W: output_channels: ex, hz")
    run = subprocess.run([sys.executable, str(PROCESS_RR), str(path), "SD", "W", "--max-period", "1000", "--tag",
                          "unit"], capture_output=True, text=True, timeout=1200)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text[-3000:]
    edi = sorted((path.parent / "work" / "tf").glob("SD_rr-W_*_unit.edi"))[-1]
    blocks = edi_blocks(edi)
    for key in ("ZYXR", "ZYXI", "ZYYR", "ZYYI", "ZYX.VAR", "ZYY.VAR"):
        assert blocks[key] and all(v == 1e32 for v in blocks[key]), (key, blocks[key][:4])
    for key in ("ZXXR", "ZXYR", "ZXY.VAR", "TXR.EXP", "TYR.EXP"):
        assert any(v != 1e32 and math.isfinite(v) for v in blocks[key]), (key, blocks[key][:4])
    emeas = next(line for line in edi.read_text(encoding="utf-8").splitlines() if "CHTYPE=ex" in line)
    fields = dict(f.split("=", 1) for f in emeas.split()[1:])
    geo = ds.diagonal_geometry(48.0, 0.0, 44.0, 90.0, 1)
    want = dict(X=0.0, Y=44.0, X2=48.0, Y2=0.0, AZM=round(geo["azimuth"], 2))
    assert all(abs(float(fields[k]) - v) < 0.006 for k, v in want.items()), emeas
    import json

    verdict = json.loads(edi.with_suffix(".json").read_text(encoding="utf-8"))["quadrant"]["verdict"]
    assert verdict.startswith("not judged") and "diagonal" in verdict, verdict
    assert "CHTYPE=ey" not in edi.read_text(encoding="utf-8"), "an EMEAS line for the ey the site did not record"
    for suffix in (".xml", ".h5"):
        assert edi.with_suffix(suffix).exists(), edi.with_suffix(suffix)
    print(f"  process_rr.py SD rr W: {edi.name}: ZYX, ZYY EMPTY at {len(blocks['ZYXR'])} periods, ZXX/ZXY and the "
          f"tipper estimated; {emeas.strip()}; no EMEAS for ey; XML and h5 written")
    # G: a diagonal of two runs (the XML writer stopped on mt_metadata's phantom ey in the first run only)
    run_script(path, "G")
    run = subprocess.run([sys.executable, str(PROCESS_RR), str(path), "GD", "W", "--max-period", "1000", "--tag",
                          "unit"], capture_output=True, text=True, timeout=1200)
    text = run.stdout + run.stderr
    assert run.returncode == 0, text[-3000:]
    edi_g = sorted((path.parent / "work" / "tf").glob("GD_rr-W_*_unit.edi"))[-1]
    from mt_workbench.products import read_tf

    back = read_tf(edi_g.with_suffix(".xml"))
    assert edi_g.with_suffix(".h5").exists() and back.impedance is not None, edi_g
    print(f"  GD (two runs) rr W: {edi_g.name}, XML and h5 written; the XML reads back")


def edi_blocks(path: Path) -> dict[str, list[float]]:
    """Return the numbers of each data block of an EDI (``>ZXYR ...`` to the next ``>`` line), by block name."""
    out, key = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            words = line[1:].split()
            key = words[0] if words else None
            if key is not None:
                out.setdefault(key, [])
            continue
        if key is not None:
            try:
                out[key].extend(float(v) for v in line.split())
            except ValueError:
                key = None
    return out


def test_one_line_patch() -> None:
    """The scoped aurora patch acts for one electric output only and restores aurora's methods."""
    import mt_workbench.process as mp

    originals = [getattr(owner, attr) for owner, attr in mp.ONE_LINE_PATCHES]
    with mp._one_electric_line(["ex", "ey", "hz"]) as added:
        assert added == [] and [getattr(o, a) for o, a in mp.ONE_LINE_PATCHES] == originals
    with mp._one_electric_line(["ex", "hz"]) as added:
        assert added == ["ey"] and all(getattr(o, a) is not f for (o, a), f in zip(mp.ONE_LINE_PATCHES, originals))
    assert [getattr(o, a) for o, a in mp.ONE_LINE_PATCHES] == originals
    print("  _one_electric_line: nothing patched for ex, ey, hz; for ex, hz both methods patched and restored")


def test_mutation(path: Path, truths: dict) -> None:
    """The wrong sign leaves 2 V in the derived ex, and the cancellation criterion catches it."""
    sv = Survey.from_yaml(path)
    out = SCRATCH / "mutant" / "SD.h5"
    out.parent.mkdir(parents=True, exist_ok=True)
    ds.write_derived(default_archive_path(sv, "S"), "S", out, -1)
    worst = cancellation(derived_samples(out, "SD"), truths["S"])
    assert worst > 1e4, worst
    print(f"  mutation (ex + ey): max |diff| {worst:.3g} words: caught")
    # the phantom ey left in place: the XML write of the two-run diagonal must fail as it did at TAS227LPD
    import datetime as dt

    import mt_workbench.process as mp
    import process_rr
    from mt_workbench.bands import build_band_scheme
    from mt_workbench.products import write_xml

    args = process_rr.build_parser().parse_args([str(path), "GD", "W", "--max-period", "1000", "--dry-run"])
    res = process_rr.resolve(args, dt.datetime.now().astimezone())
    real = mp._drop_unrecorded_lines
    mp._drop_unrecorded_lines = lambda tf, names: []
    try:
        tf = mp.process_station(default_archive_path(sv, "GD"), "GD", default_archive_path(sv, "W"), "W",
                                band_scheme=build_band_scheme(10.0, **res["scheme_kwargs"]),
                                output_channels=res["output_channels"], site=sv.site("GD"))
    finally:
        mp._drop_unrecorded_lines = real
    try:
        write_xml(tf, SCRATCH / "mutant" / "GD_phantom.xml")
    except AttributeError as exc:
        print(f"  mutation (the phantom ey kept): the XML write fails ({exc}): caught")
    else:
        raise AssertionError("the XML of a two-run diagonal with the phantom ey was written: the test cannot fail")


if __name__ == "__main__":
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr, level="ERROR")
    print("This test fails if" + __doc__.split("This test fails if", 1)[1].split("\n\nMutation")[0])
    print()
    test_geometry()
    print("  ok  test_geometry")
    test_one_line_patch()
    print("  ok  test_one_line_patch")
    root = SCRATCH / "survey"
    shutil.rmtree(root, ignore_errors=True)
    survey_path, site_truths = build(root)
    test_chains(survey_path)
    print("  ok  test_chains")
    test_script(survey_path, site_truths)
    print("  ok  test_script")
    test_mutation(survey_path, site_truths)
    print("  ok  test_mutation")
    print("\nPASS  diagonal_site_unit (5 tests)")
