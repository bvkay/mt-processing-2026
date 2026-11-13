# -*- coding: utf-8 -*-
"""
Unit test for the View tensors tab (mt_workbench.gui.tabs.tensors) and mt_workbench.intersite.draw_estimate

Runs headless on a scratch survey of five sites, 20 min at 100 Hz, with
the fields of tests/intersite_unit.py: the pair L, B with a known telluric
tensor, a reference R, a second stack member S1, and X, a copy of L with
its ex and ey exchanged. L declares azimuths of 10 and 100 deg and a
declination, and masks.yaml holds one entry on X, limited to the periods
under 1 s. scripts/process_intersite.py writes five products into the
workspace's tf folder: the telluric and the magnetic tensor of L on B, the
telluric tensor of X on B with a tag, the telluric tensor of L on the E
stack of B and S1, and the telluric tensor of L on B referenced to the H
stack of R and S1. At 20 min the longest periods cannot be estimated and
the level before them has fewer than five jackknife groups. Each product
of L therefore holds periods without a flag, flagged periods and periods
that were not estimated, and the product of X holds two flags on every
estimated period (off-diagonal, negative real determinant) and a third
on three of them.

The test then writes into the same folder what the tab must sort out: an
EDI with its sidecar and a CSV of the same stem, a CSV and a sidecar of an
impedance under a tensor's file name, a CSV with no sidecar, a copy of a
product under a plain file name, a product whose sidecar is cut short, one
whose CSV is not a tensor's and one whose CSV holds its header and no row.
`MainWindow` is built on the survey. No job is started: `JobRunner.run_now`
is recorded, and the finished job of criterion 9 is a signal sent by hand.
Every expected value is read here from the sidecar with json and from the
CSV with plain pandas, not with the package's readers.

Usage:
    QT_QPA_PLATFORM=offscreen python tests/view_tensors_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. (the tab) the window's tab after "View EDIs" is not "View tensors", or
   opening the survey does not fill its list;
2. (the list) the rows are not exactly the five products and the copy
   under a plain file name, grouped by local site and sorted by local,
   base, reference, window, tensor and tag; or the EDI, the impedance
   under a tensor's file name or the CSV with no sidecar is listed;
3. (the row) a row's local, reference, tensor, tag or window differs from
   its sidecar's, or its base from the sidecar's base site (for the stack,
   from the name the script put in the stem, "stackE");
4. (the facts) the text beside the figure lacks the local, the base, the
   reference (a site with its channels, or a stack with its members) or
   the window of the sidecar, the base stack's members, the periods
   estimated and in the layout as the CSV counts them, a flag's row
   count, the entry of masks.yaml applied to X with its windows, the
   words "as recorded, not rotated", a site's azimuths, layout north or
   declination (with "recorded and not applied" when it has one), or says
   other than the sidecar whether the timing delay was determined;
5. (arg(det) / 2) the points of the third panel, read back from the
   figure's artists, differ from the CSV's period and half_arg_det_deg on
   its estimated rows, or the error bars from half_arg_det_err_deg;
6. (flags) for a flag of the CSV, the flag's own marker is not at exactly
   the periods it marks, is not open, or the legend does not name the
   flag with its count; a curve's open markers are not at exactly the
   periods with any flag; a flagged period is missing from a curve or
   lies outside its panel's axes; or no product has a period with a flag
   and one without, or none has two flags marking different periods (so
   the rule was not put to the test);
7. (not estimated) an artist of the figure holds a period the CSV marks
   as not estimated, the legend does not count those periods, or no
   product has such a period;
8. (the magnitudes) the first panel of the magnetic product does not
   show the magnitudes of M less the identity, or that of a telluric
   product the magnitudes of the elements themselves, or the second
   panel not the phases of the elements; or, as the control that the
   comparison can fail, |M_xx| is within 0.5 of |M_xx - 1| at the median
   period;
9. (reload) a product written after the tab was made is listed before
   Reload is pressed (the control), or is not listed after; a product
   written again under its stem keeps its earlier row after Reload; a
   failed job of process_intersite.py rereads the folder, or one that
   ended well does not;
10. (not readable) the product with the cut sidecar is not listed under
    "cannot be read" with the file's name in its reason, or choosing it,
    the product with a CSV of another layout or the one with a CSV of no
    row raises, leaves axes on the figure, or does not name the file and
    say what to do;
11. (one drawing function) `intersite.plot_estimate`, which writes the
    script's figure, or the tab does not draw through
    `intersite.draw_estimate`, or no PNG is written;
12. (View EDIs) the View EDIs tab lists anything but the one EDI;
13. any Qt slot raised, or a job was started.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("QT_QPA_PLATFORM") == "offscreen" and sys.platform == "win32":
    os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")

from matplotlib.colors import to_rgba  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from _scratch import scratch_dir  # noqa: E402
from intersite_unit import FS2, T_START, fields, write_site  # noqa: E402
from mt_workbench import intersite  # noqa: E402
from mt_workbench.gui import theme  # noqa: E402
from mt_workbench.gui.app import MainWindow  # noqa: E402
from mt_workbench.gui.jobs import Job, JobRunner  # noqa: E402
from mt_workbench.gui.tabs import tensors  # noqa: E402

SCRIPT = REPO / "scripts" / "process_intersite.py"
SCRATCH = scratch_dir("view_tensors_unit")
WORK = SCRATCH / "survey" / "work"
TF = WORK / "tf"
FLAGS = ("flag_few_groups", "flag_low_coherence", "flag_off_diagonal", "flag_re_det_negative")
ELEMENTS = ("xx", "xy", "yx", "yy")
# the five runs of the script: (stem it must write, arguments after survey.yaml)
RUNS = [("L_te-B_rr-R", ["L", "B", "--kind", "telluric", "--remote", "R"]),
        ("L_hm-B_rr-R", ["L", "B", "--kind", "magnetic", "--remote", "R"]),
        ("X_te-B_rr-R_swap", ["X", "B", "--kind", "telluric", "--remote", "R", "--tag", "swap"]),
        ("L_te-stackE_rr-R", ["L", "--kind", "telluric", "--base-stack", "E", "--exclude", "R,X", "--remote", "R"]),
        ("L_te-B_rr-stackH_refstack", ["L", "B", "--kind", "telluric", "--remote-stack", "H", "--exclude", "X",
                                       "--tag", "refstack"])]
PLAIN, CUT_SIDECAR, CUT_CSV, NO_ROWS = "plain_name", "cut_sidecar", "cut_csv", "no_rows"
LATE, LATER = "late", "later"
EDI_STEM = "L_rr-R_20240301-0000"

SURVEY_YAML = """name: view_tensors_unit
instrument: lemi423
sample_rate: 100
data_root: {root}
workspace: {work}
defaults:
  channels: [ex, ey, hx, hy]
sites:
  L: {{latitude: -31.0, longitude: 137.0, azimuth_ex: 10.0, azimuth_ey: 100.0, declination: 7.5}}
  B: {{latitude: -31.01, longitude: 137.0}}
  R: {{latitude: -31.5, longitude: 137.2}}
  S1: {{latitude: -31.2, longitude: 137.1}}
  X: {{latitude: -31.0, longitude: 137.01}}
processing:
  min_period: 0.04
  max_period: 200.0
  periods_per_decade: 10.0
"""

failures: list[str] = []
SLOT_ERRORS: list[str] = []
STARTED: list[list[str]] = []
# a job the window would start at once (the basemap fetch) is recorded, not run
JobRunner.run_now = lambda self, label, argv, **details: STARTED.append([str(a) for a in argv]) or -1


def check(ok: bool, msg: str) -> bool:
    """Print a PASS/FAIL line and record a failure."""
    print(("PASS " if ok else "FAIL ") + msg)
    if not ok:
        failures.append(msg)
    return bool(ok)


def _slot_error(kind, value, tb) -> None:
    """Record an exception raised in a Qt slot, and print it."""
    SLOT_ERRORS.append(f"{kind.__name__}: {value}")
    traceback.print_exception(kind, value, tb)


sys.excepthook = _slot_error


def pump(app: QApplication, seconds: float = 0.2) -> None:
    """Let queued signals and layout work run."""
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()


# ------------------------------------------------------------------ the survey and its products


def build_survey() -> Path:
    """Write the scratch survey, its five archives and masks.yaml; return survey.yaml."""
    import yaml

    shutil.rmtree(SCRATCH / "survey", ignore_errors=True)
    root = SCRATCH / "survey" / "raw"
    root.mkdir(parents=True)
    WORK.mkdir(parents=True)
    (WORK / "basemap.json").write_text("{}", encoding="utf-8")  # no basemap fetch on open
    yaml_path = SCRATCH / "survey" / "survey.yaml"
    yaml_path.write_text(SURVEY_YAML.format(root=root.as_posix(), work=WORK.as_posix()), encoding="utf-8")
    spec = fields(FS2, 1.0 / 3.0, seed=31, h_sites=("l", "b", "r", "s1"))
    spec["scale"] = 1.0e4 / float(np.std(np.fft.irfft(spec["b_ex"], spec["n"])))
    spec.update(x_ex=spec["l_ey"], x_ey=spec["l_ex"], x_hx=spec["l_hx"], x_hy=spec["l_hy"])
    for site in ("L", "B", "R", "S1", "X"):
        write_site(WORK, site, spec, T_START, spec["n"])
    start, end = (T_START + pd.Timedelta(seconds=s) for s in (300, 330))
    masks = {"X": [{"start": f"{start.isoformat()}Z", "end": f"{end.isoformat()}Z", "bands": [0.04, 1.0],
                    "reason": "test", "found_by": "time", "scope": "local"}]}
    (yaml_path.parent / "masks.yaml").write_text(yaml.safe_dump(masks, sort_keys=False), encoding="utf-8")
    return yaml_path


def run_script(yaml_path: Path) -> bool:
    """Run the five script runs into the workspace's tf folder; False when one fails or writes another stem."""
    good = True
    for stem, args in RUNS:
        res = subprocess.run([sys.executable, str(SCRIPT), str(yaml_path), *args], capture_output=True, text=True,
                             cwd=REPO)
        written = all((TF / f"{stem}{suffix}").exists() for suffix in (".csv", ".json", ".h5", ".png"))
        if not check(res.returncode == 0 and written, f"   the script wrote {stem} (exit {res.returncode})"):
            print(res.stdout[-1500:], res.stderr[-1500:])
            good = False
    return good


def copy_product(source: str, stem: str, tag: str) -> None:
    """Copy a product's four files under another stem, its sidecar carrying `tag`."""
    for suffix in (".csv", ".h5", ".png"):
        shutil.copy2(TF / f"{source}{suffix}", TF / f"{stem}{suffix}")
    side = sidecar(source)
    side["tag"] = tag
    (TF / f"{stem}.json").write_text(json.dumps(side), encoding="utf-8")


def write_others() -> None:
    """Write the files the tab must leave out, the plain-named copy and the two products that do not read."""
    (TF / f"{EDI_STEM}.edi").write_text("fake EDI\n", encoding="utf-8")
    (TF / f"{EDI_STEM}.json").write_text(json.dumps({"edi": f"{EDI_STEM}.edi", "engine": "aurora"}),
                                         encoding="utf-8")
    (TF / f"{EDI_STEM}.csv").write_text("period,flag\n1.0,False\n", encoding="utf-8")
    (TF / "Z_te-B_rr-R.csv").write_text("period,flag\n1.0,False\n", encoding="utf-8")
    (TF / "Z_te-B_rr-R.json").write_text(json.dumps({"edi": "Z.edi", "engine": "aurora"}), encoding="utf-8")
    (TF / "stray.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    copy_product(RUNS[0][0], PLAIN, "renamed")
    copy_product(RUNS[0][0], CUT_SIDECAR, "cut")
    text = (TF / f"{RUNS[0][0]}.json").read_text(encoding="utf-8")
    (TF / f"{CUT_SIDECAR}.json").write_text(text[: len(text) // 2], encoding="utf-8")
    copy_product(RUNS[0][0], CUT_CSV, "csv")
    (TF / f"{CUT_CSV}.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    copy_product(RUNS[0][0], NO_ROWS, "header")
    header = (TF / f"{RUNS[0][0]}.csv").read_text(encoding="utf-8").splitlines()[0]
    (TF / f"{NO_ROWS}.csv").write_text(header + "\n", encoding="utf-8")


def sidecar(stem: str) -> dict:
    """Return a product's sidecar, read with json."""
    return json.loads((TF / f"{stem}.json").read_text(encoding="utf-8"))


def table(stem: str) -> pd.DataFrame:
    """Return a product's CSV, read with plain pandas."""
    return pd.read_csv(TF / f"{stem}.csv")


# ------------------------------------------------------------------ reading the tab back


def listed(tab) -> dict[str, list[str]]:
    """Return {stem: its row's cells} of the tab's product rows, in the tree's order."""
    return {item.data(0, Qt.UserRole)["stem"]: [item.text(c) for c in range(len(tensors.COLUMNS))]
            for item in tab.rows()}


def groups(tab) -> list[tuple[str, list[str]]]:
    """Return [(group text, the stems under it)] of the tree, top to bottom."""
    out = []
    for k in range(tab.tree.topLevelItemCount()):
        top = tab.tree.topLevelItem(k)
        out.append((top.text(0), [top.child(r).data(0, Qt.UserRole)["stem"] for r in range(top.childCount())]))
    return out


def choose(tab, stem: str) -> bool:
    """Make a product's row the current one, as a click does; False when the tree has no such row."""
    item = next((item for item in tab.rows() if item.data(0, Qt.UserRole)["stem"] == stem), None)
    if item is not None:
        tab.tree.setCurrentItem(item)
    return item is not None


def drawn(fig, gid: str) -> list:
    """Return the figure's artists carrying a gid."""
    return fig.findobj(match=lambda artist: artist.get_gid() == gid)


def points(artist) -> tuple[np.ndarray, np.ndarray]:
    """Return the (x, y) of a line."""
    return np.asarray(artist.get_xdata(), dtype=float), np.asarray(artist.get_ydata(), dtype=float)


def same(a, b, tol: float = 1e-9) -> bool:
    """True when two arrays have one shape and agree to `tol` (relative to 1 or to the value)."""
    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    return a.shape == b.shape and bool(np.all(np.abs(a - b) <= tol * np.maximum(1.0, np.abs(b))))


def legend_texts(fig) -> list[str]:
    """Return every legend text of the figure: the one above the first panel and the one below the third."""
    legends = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend() is not None]
    return [text.get_text() for legend in legends for text in legend.get_texts()]


# ------------------------------------------------------------------ the criteria


def check_rows(tab) -> None:
    """Criteria 2 and 3: what is listed, in which order, and each row against its sidecar."""
    stems = [stem for stem, _args in RUNS] + [PLAIN, CUT_CSV, NO_ROWS]
    rows = listed(tab)
    readable = {stem: cells for stem, cells in rows.items() if stem != CUT_SIDECAR}
    check(sorted(readable) == sorted(stems),
          f"2 listed: {sorted(readable)}; left out {EDI_STEM}, Z_te-B_rr-R and stray")
    keys = {}
    for stem in stems:
        side = sidecar(stem)
        base = side["base_site"] or RUNS[3][0].split("_te-")[1].split("_rr-")[0]  # the stem's "stackE"
        window = " to ".join(side["window"][k][:19].replace("T", " ") for k in ("start", "end"))
        want = [side["local"], base, side["remote"], side["kind"], side["tag"] or "", window]
        check(rows.get(stem) == want, f"3 row of {stem}: {rows.get(stem)}, the sidecar gives {want}")
        keys[stem] = (side["local"], base, side["remote"], side["window"]["start"], side["kind"], side["tag"] or "",
                      stem)
    order = sorted(stems, key=keys.get)
    locals_ = sorted({key[0] for key in keys.values()})
    want_groups = [(local, [s for s in order if keys[s][0] == local]) for local in locals_]
    got = groups(tab)
    check(got[: len(want_groups)] == want_groups, f"2 groups by local site, sorted: {got[: len(want_groups)]}")
    check(rows.get(RUNS[3][0], [None, None])[1] == "stackE", f"3 the stack's row reads base "
                                                             f"{rows.get(RUNS[3][0], [None, None])[1]!r} (stackE)")


def check_facts(tab, stem: str) -> None:
    """Criterion 4 on the product now drawn."""
    side, df, text = sidecar(stem), table(stem), tab.facts.toPlainText()
    lines = text.splitlines()
    window = [side["window"][k][:19].replace("T", " ") for k in ("start", "end")]
    estimated = int((~df["flag_not_estimated"].astype(bool)).sum())
    reference = side["reference"]
    detail = (f", a stack of {len(reference['members'])} sites ({', '.join(m['site'] for m in reference['members'])})"
              if reference["type"] == "stack" else f" ({', '.join(reference['channels'])})")
    wanted = [f"local: {side['local']}", f"reference: {side['remote']}{detail}", window[0], window[1],
              f"periods: {estimated} estimated of the {len(df)} in the layout", "as recorded, not rotated"]
    missing = [w for w in wanted if w not in text]
    check(not missing, f"4 facts of {stem}: sites, window and periods as the sidecar and the CSV give them "
                       f"(missing {missing})")
    flag_lines = [line.strip() for line in lines if line.startswith("    ") and line.strip().split(": ")[-1].isdigit()]
    counts = [int(line.split(": ")[-1]) for line in flag_lines[: len(FLAGS)]]
    in_csv = [int(df[flag].astype(bool).sum()) for flag in FLAGS]
    check(counts == [side["flags"][flag]["rows"] for flag in FLAGS] == in_csv,
          f"4 facts of {stem}: flag rows {counts}, the sidecar and the CSV give {in_csv}")
    for site, frame in side["frames"]["sites"].items():
        head = "frames: as recorded, not rotated"
        after = lines[lines.index(head):] if head in lines else []
        line = next((ln for ln in after if ln.strip().startswith(f"{site} (")), "")
        declination = ("declination not recorded" if frame["declination"] is None else
                       f"declination {frame['declination']} deg, recorded and not applied")
        parts = [str(frame["azimuth_ex"]), str(frame["azimuth_ey"]), f"{frame['layout_north']} north", declination]
        check(all(p in line for p in parts), f"4 facts of {stem}: frame of {site}: {line.strip()!r}")
    applied = {site: entry for site, entry in side["masks"]["sites"].items() if entry["applied"]}
    if applied:
        for site, entry in applied.items():
            want = f"{site} ({entry['role']}): {len(entry['applied'])} masks.yaml entry, {entry['windows_masked']} band"
            check(want in text, f"4 facts of {stem}: masks line {want!r}")
    else:
        check("masks: no masks.yaml entry applied" in text, f"4 facts of {stem}: no mask applied")
    word = {True: "timing delay: determined", False: "timing delay: not determined"}[side["timing_check"]["determined"]]
    check(word in lines, f"4 facts of {stem}: {word!r} as the sidecar says")
    if side["base_stack"]:
        members = [m["site"] for m in side["base_stack"]["members"]]
        check(f"base: stackE, a stack of {len(members)} sites ({', '.join(members)})" in text,
              f"4 facts of {stem}: the stack and its members {members}")
    else:
        check(f"base: {side['base_site']}" in lines, f"4 facts of {stem}: base {side['base_site']}")


def check_figure(tab, stem: str) -> dict:
    """Criteria 5 to 8 on the product now drawn; return its counts of periods."""
    fig, df, side = tab.figure, table(stem), sidecar(stem)
    letter = side["tensor"]
    est = ~df["flag_not_estimated"].astype(bool).to_numpy()
    period = df["period"].to_numpy()
    any_flag = np.any([df[flag].astype(bool).to_numpy() for flag in FLAGS], axis=0)
    counts = {"estimated": int(est.sum()), "not estimated": int((~est).sum()), "flagged": int(any_flag.sum()),
              "clean": int((est & ~any_flag).sum())}
    if not check(len(fig.axes) == 3 and len(drawn(fig, "psi")) == 1 and len(drawn(fig, "psi_error")) == 1,
                 f"5 {stem}: three panels with arg(det) / 2 and its bars"):
        return counts
    top, middle, bottom = fig.axes
    texts = legend_texts(fig)

    # 5. arg(det) / 2 and its error bars
    x, y = points(drawn(fig, "psi")[0])
    check(same(x, period[est]) and same(y, df["half_arg_det_deg"].to_numpy()[est]),
          f"5 {stem}: arg(det) / 2 drawn at the CSV's {int(est.sum())} estimated periods with its values")
    # a bar with no finite end has no point in its segment
    segments = [seg for seg in drawn(fig, "psi_error")[0].get_segments() if len(seg) == 2]
    bars = np.array([[seg[0][0], (seg[1][1] - seg[0][1]) / 2.0, (seg[1][1] + seg[0][1]) / 2.0] for seg in segments])
    bars = bars.reshape(-1, 3)
    bars = bars[np.isfinite(bars).all(axis=1)]  # a period with too few groups for an error has no bar
    finite = est & np.isfinite(df["half_arg_det_err_deg"].to_numpy())
    check(bars.shape == (int(finite.sum()), 3) and same(bars[:, 0], period[finite])
          and same(bars[:, 1], df["half_arg_det_err_deg"].to_numpy()[finite])
          and same(bars[:, 2], df["half_arg_det_deg"].to_numpy()[finite]),
          f"5 {stem}: {len(bars)} error bars of the CSV's half_arg_det_err_deg, centred on the points")

    # 6. each flag's own marker, the open markers of every curve, nothing hidden
    for flag in FLAGS:
        rows = df[flag].astype(bool).to_numpy()
        marks = drawn(fig, flag)
        if not rows.any():
            check(not marks, f"6 {stem}: no {flag} marker (no period carries it)")
            continue
        words = intersite.FLAG_MARKS[flag][0]
        ok = len(marks) == 1 and marks[0].axes is bottom
        if ok:
            fx, fy = points(marks[0])
            ok = (same(fx, period[rows]) and same(fy, df["half_arg_det_deg"].to_numpy()[rows])
                  and marks[0].get_markerfacecolor() == "none" and marks[0].get_marker() not in ("", "None", None))
        check(ok and f"{words}: {int(rows.sum())}" in texts,
              f"6 {stem}: {flag} marked open at its {int(rows.sum())} periods and named in the legend")
    opens = drawn(fig, "flagged")
    ok = len(opens) == 9
    for line in opens:
        face, edge = to_rgba(line.get_markerfacecolor()), to_rgba(line.get_markeredgecolor())
        ok = ok and same(points(line)[0], period[any_flag]) and face == to_rgba(line.axes.get_facecolor()) != edge
    check(ok, f"6 {stem}: the open markers of the nine curves at the {int(any_flag.sum())} flagged periods")
    curves = {gid: points(drawn(fig, gid)[0]) for gid in ["psi"] + [f"{part}_{el}" for part in ("abs", "arg")
                                                                     for el in ELEMENTS]}
    hidden = []
    for gid, (cx, cy) in curves.items():
        ax = bottom if gid == "psi" else (top if gid.startswith("abs") else middle)
        (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
        if not (same(cx, period[est]) and np.all(np.isfinite(cy)) and np.all((cx > x0) & (cx < x1))
                and np.all((cy >= y0) & (cy <= y1))):
            hidden.append(gid)
    check(not hidden, f"6 {stem}: every estimated period, flagged or not, on each curve and inside its panel "
                      f"(not so: {hidden})")

    # 7. no artist holds a period that was not estimated
    lines = fig.findobj(match=lambda a: a.get_gid() is not None and hasattr(a, "get_xdata"))
    held = [line.get_gid() for line in lines
            if np.isin(np.round(points(line)[0], 9), np.round(period[~est], 9)).any()]
    check(not held, f"7 {stem}: no artist at the {int((~est).sum())} periods not estimated (holding one: {held})")
    if (~est).any():
        check(f"not estimated, no value to draw: {int((~est).sum())}" in texts,
              f"7 {stem}: the legend counts the {int((~est).sum())} periods not estimated")

    # 8. the magnitudes: of M less the identity, of T itself
    wrong = []
    for k, el in enumerate(ELEMENTS):
        re, im = df[f"{letter}_{el}_re"].to_numpy()[est], df[f"{letter}_{el}_im"].to_numpy()[est]
        less = 1.0 if (letter == "M" and el in ("xx", "yy")) else 0.0
        if not same(curves[f"abs_{el}"][1], np.hypot(re - less, im)):
            wrong.append(el)
        if not same(curves[f"arg_{el}"][1], np.degrees(np.arctan2(im, re))):
            wrong.append(f"arg {el}")
    what = "M less the identity" if letter == "M" else "the elements"
    check(not wrong, f"8 {stem}: the first panel shows the magnitudes of {what}, the second the phases (not so: "
                     f"{wrong})")
    if letter == "M":
        re, im = df["M_xx_re"].to_numpy()[est], df["M_xx_im"].to_numpy()[est]
        gap = float(np.median(np.abs(np.hypot(re, im) - np.hypot(re - 1.0, im))))
        check(gap > 0.5, f"8 control: |M_xx| is {gap:.2f} from |M_xx - 1| at the median period, so the comparison "
                         f"can fail")
        check("less the identity" in top.get_ylabel() and "magnetic tensor" in top.get_ylabel(),
              f"8 {stem}: the first panel is labelled {top.get_ylabel()!r}")
    else:
        check("telluric tensor" in top.get_ylabel() and "identity" not in top.get_ylabel(),
              f"8 {stem}: the first panel is labelled {top.get_ylabel()!r}")
    return counts


def check_reload(tab, runner) -> None:
    """Criterion 9: Reload, and the reread after a finished job of process_intersite.py."""
    copy_product(RUNS[1][0], LATE, "late")
    check(LATE not in listed(tab), "9 control: a product written after the tab was made is not listed yet")
    tab.reload_button.click()
    check(LATE in listed(tab) and listed(tab)[LATE][4] == "late", "9 Reload lists it")
    side = sidecar(LATE)
    side["tag"] = "again"
    (TF / f"{LATE}.json").write_text(json.dumps(side), encoding="utf-8")
    tab.reload_button.click()
    check(listed(tab).get(LATE, [""] * 6)[4] == "again",
          f"9 a product written again is read again: its row's tag reads {listed(tab).get(LATE, [''] * 6)[4]!r}")
    copy_product(RUNS[1][0], LATER, "later")
    argv = [sys.executable, str(SCRIPT), "survey.yaml", "L", "B", "--kind", "magnetic", "--remote", "R"]
    runner.jobs.append(Job(label="tensor job", argv=argv, status="failed"))
    runner.job_finished.emit(len(runner.jobs) - 1, False)
    check(LATER not in listed(tab), "9 a failed job of process_intersite.py does not reread the folder")
    runner.jobs.append(Job(label="tensor job", argv=argv, status="done"))
    runner.job_finished.emit(len(runner.jobs) - 1, True)
    check(LATER in listed(tab), "9 a job of process_intersite.py that ended well rereads the folder")


def check_unreadable(tab) -> None:
    """Criterion 10: the cut sidecar and the CSV of another layout."""
    last = (groups(tab) or [("", [])])[-1]
    row = next((item for item in tab.rows() if item.data(0, Qt.UserRole)["stem"] == CUT_SIDECAR), None)
    check(last == (tensors.UNREADABLE, [CUT_SIDECAR]) and row is not None and f"{CUT_SIDECAR}.json" in row.text(0),
          f"10 the cut sidecar is listed last under {last[0]!r}: {row.text(0)[:90] if row is not None else None!r}")
    for stem, name in ((CUT_SIDECAR, f"{CUT_SIDECAR}.json"), (CUT_CSV, f"{CUT_CSV}.csv"),
                       (NO_ROWS, f"{NO_ROWS}.csv")):
        before = len(SLOT_ERRORS)
        there = choose(tab, stem)
        text = tab.facts.toPlainText()
        check(there and len(SLOT_ERRORS) == before and not tab.figure.axes and name in text
              and "cannot be read" in text and "Run the pair again" in text and name in tab.status_label.text(),
              f"10 choosing {stem}: no axes, nothing raised, the reason and what to do: {text.splitlines()[0][:100]!r}")


def check_one_function(tab) -> None:
    """Criterion 11: the script's figure and the tab draw through `intersite.draw_estimate`."""
    calls = []
    real = intersite.draw_estimate

    def recording(fig, est, letter, **keywords):
        calls.append(letter)
        return real(fig, est, letter, **keywords)

    intersite.draw_estimate = recording
    try:
        est, letter = intersite.read_csv(TF / f"{RUNS[0][0]}.csv")
        png = intersite.plot_estimate(est, letter, SCRATCH / "figure.png", title="check",
                                      timing=sidecar(RUNS[0][0])["timing_check"])
        on_disk = list(calls)
        choose(tab, RUNS[1][0])
    finally:
        intersite.draw_estimate = real
    check(on_disk == ["T"] and png.exists() and png.stat().st_size > 20_000,
          f"11 plot_estimate drew through draw_estimate ({on_disk}) and wrote {png.name}")
    check(calls == ["T", "M"], f"11 the tab drew through draw_estimate ({calls[1:]})")


def main() -> int:
    """Build the survey and its products, drive the tab, and return 1 on any failure."""
    print(__doc__.split("**This test fails if**")[1].rstrip())
    print()
    started = time.time()
    yaml_path = build_survey()
    if not run_script(yaml_path):
        print("FAIL the products could not be made")
        return 1
    write_others()
    print(f"   survey and products written in {time.time() - started:.0f} s: {TF}")
    app = QApplication.instance() or QApplication(sys.argv)
    theme.apply(app)
    window = MainWindow(survey_yaml=yaml_path)
    window.resize(1400, 900)
    window.show()
    pump(app)
    tab = window.tensors_tab

    titles = [window.tabs.tabText(k) for k in range(window.tabs.count())]
    after = titles.index("View EDIs") + 1 if "View EDIs" in titles else 0
    check(titles[after: after + 1] == ["View tensors"] and window.tabs.widget(after) is tab,
          f"1 the tab after View EDIs: {titles[after: after + 1]}")
    check(len(listed(tab)) > 0, f"1 opening the survey filled the list ({len(listed(tab))} rows)")
    check_rows(tab)

    totals = {"not estimated": 0, "mixed": 0}
    for stem, _args in RUNS:
        if not check(choose(tab, stem), f"2 the row of {stem} is there to choose"):
            continue
        pump(app, 0.05)
        counts = check_figure(tab, stem)
        check_facts(tab, stem)
        totals["not estimated"] += counts["not estimated"] > 0
        totals["mixed"] += counts["flagged"] > 0 and counts["clean"] > 0
        print(f"   {stem}: {counts}")
    check(totals["mixed"] >= 2, f"6 {totals['mixed']} products hold periods with a flag beside periods without")
    check(totals["not estimated"] == len(RUNS), f"7 {totals['not estimated']} products hold periods not estimated")
    swap = table(RUNS[2][0])
    est = ~swap["flag_not_estimated"].astype(bool)
    few = int(swap.loc[est, "flag_few_groups"].sum())
    check(bool(swap.loc[est, "flag_off_diagonal"].all() and swap.loc[est, "flag_re_det_negative"].all())
          and 0 < few < int(est.sum()),
          f"6 the exchanged product carries two flags on each of its {int(est.sum())} estimated periods and a third "
          f"on {few}, so the flags mark different periods")

    check_reload(tab, window.state.runner)
    check_unreadable(tab)
    check_one_function(tab)

    window.edis_tab.reload()
    tree = window.edis_tab.tree
    tops = [tree.topLevelItem(k) for k in range(tree.topLevelItemCount())]
    edis = [Path(str(top.child(r).data(0, Qt.UserRole))).name for top in tops for r in range(top.childCount())]
    check(edis == [f"{EDI_STEM}.edi"], f"12 the View EDIs tab lists {edis}")

    shot = SCRATCH / "view_tensors_tab.png"
    choose(tab, RUNS[2][0])
    window.tabs.setCurrentWidget(tab)
    pump(app, 0.3)
    window.grab().save(str(shot))
    window.close()
    pump(app, 0.2)
    check(not SLOT_ERRORS, f"13 no Qt slot raised: {SLOT_ERRORS}")
    check(all(Path(argv[1]).name == "fetch_basemap.py" for argv in STARTED) and not any(
        job.status == "running" for job in window.state.runner.jobs), f"13 no job started: {STARTED}")
    print(f"   the tab on {RUNS[2][0]}: {shot}")
    if failures:
        print(f"\nFAIL  view_tensors_unit ({len(failures)} failure(s))")
        for msg in failures:
            print("  " + msg)
        return 1
    print(f"\nPASS  view_tensors_unit ({time.time() - started:.0f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
