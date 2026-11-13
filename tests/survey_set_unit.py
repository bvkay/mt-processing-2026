# -*- coding: utf-8 -*-
"""
Unit test for scripts/survey_set.py

Runs the command on a synthetic survey.yaml built here, in the test's scratch
folder, and reads the file back after each run: the parsed value and its type,
the bytes when nothing may change, survey.yaml.previous, and `Survey.site` with
no data folder. Most runs call the script's `main` in this process; two run it
as a command, to read the exit code the shell sees.

Usage:
    python tests/survey_set_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

- `serial=036` is not written as the text '036', or `firmware=2.10` as the
  text '2.10';
- `notes=moved 20 m: east`, `notes=yes` or `remote=on` is not written as that
  text;
- `notes=# taped` removes the key, or does not write the text '# taped';
- `dipole_length_ex=52` is not the number 52.0, `swap_h=true` not the bool
  True, or `flip_h=[hy]` not the list [hy];
- `rot_h=abc`, `dipole_length_ex=abc`, `flip_h=hy`, `channels=ex` (not a
  list) or `swap_h=1` is not refused with exit 2, the file untouched and the
  key named in the message; `dipole_length_ex=abc` and `channels=ex` are values
  `Survey.site` accepts, so only the command's own parsing can refuse them;
- `dipole_length_ex=50 m` typed without quotes (the `m` a word of its own),
  `dipole_length=46` (no such key) or `dipole_length_ex=50m` is not refused
  with exit 2 and a message that says what to type: quotes around a value
  with a space, the closest key names, or the number alone with no unit;
- `notes=` does not remove the key;
- an unknown key (`bogus_key=1`, and `bogus_key=` with nothing to remove) is
  not refused with exit 2 and the file untouched;
- `defaults azimuth_ey=91` without `--yes` writes anything, or does not print
  the sites that keep 90 (S02 and S03, not S01, which has its own 95);
- `defaults azimuth_ey=91 --yes` does not write 91 into `defaults:` and 90
  into S02 and S03, leaves `Survey.site` of any site with another azimuth,
  does not keep the old bytes in survey.yaml.previous, or does not print
  where they are;
- `--add S04 latitude=-31.3`, with a folder S04 under `data_root`, does not
  add the entry, or a site with no entry is not refused without `--add`;
- `--add S05 latitude=-31.3`, with no folder S05 under `data_root` (a
  mistyped name), is not refused with exit 2, the file untouched and the
  folder it looked for named; or `--add S02L derived_from=S02
  sample_rate=1.0` and `--add S02H bursts_of=S02 sample_rate=24000`, which
  have no folder by design, are refused;
- a request that changes nothing exits other than 0 or changes a byte;
- run as a command, a refused value does not exit 2 or a written one exit 0.

The mutations this test catches, each made in a copy of the script: every
value parsed with a bare ``yaml.safe_load`` (the `036` item fails); the
folder of an added site not looked for (the S05 item fails); a derived or
burst site asked for its folder too (the S02L and S02H items fail).
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tests"))

from mt_workbench.survey import Survey  # noqa: E402
from _scratch import scratch_dir  # noqa: E402

SCRIPT = REPO / "scripts" / "survey_set.py"

TEXT = """\
# survey for the survey_set test
name: t_set
instrument: lemi423
sample_rate: 1000
data_root: X
defaults:
  dipole_length_ex: 50.0
  dipole_length_ey: 50.0
  azimuth_ex: 0.0
  azimuth_ey: 90.0
  channels: [ex, ey, hx, hy]
sites:
  S01:
    latitude: -31.0
    azimuth_ey: 95.0
    notes: field sheet 3
  # the second line
  S02:
    latitude: -31.1
  S03:
    latitude: -31.2
    serial: '101'
"""

SCRATCH = scratch_dir("survey_set_unit")
failed: list[str] = []
n_checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global n_checks
    n_checks += 1
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}{': ' + detail if detail else ''}")
    if not ok:
        failed.append(name)


def load_script():
    spec = importlib.util.spec_from_file_location("survey_set", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def put(case: str, text: str = TEXT) -> Path:
    folder = SCRATCH / case
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    path = folder / "survey.yaml"
    path.write_bytes(text.encode("utf-8"))
    return path


def run(script, path: Path, *args: str) -> tuple[int, str]:
    """Run the script's main in this process; return (exit code, stdout and stderr)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            code = script.main([str(path), *args])
        except SystemExit as exc:  # argparse leaves through SystemExit
            code = exc.code
    return code, out.getvalue()


def parsed(path: Path) -> dict:
    return yaml.safe_load(path.read_bytes().decode("utf-8"))


def entry(path: Path, site: str) -> dict:
    return parsed(path)["sites"][site] or {}


def site(path: Path, name: str):
    config = {**parsed(path), "data_root": str(SCRATCH / "no_data_root")}
    return Survey(config, path.parent).site(name)


def untouched(path: Path) -> bool:
    previous = path.with_name(path.name + ".previous")
    return path.read_bytes() == TEXT.encode("utf-8") and not previous.exists()


# ------------------------------------------------------------------ the cases


def test_text(script) -> None:
    path = put("text")
    code, out = run(script, path, "S02", "serial=036", "firmware=2.10", "remote=on", "notes=moved 20 m: east")
    got = entry(path, "S02")
    check("serial=036 is the text '036'", code == 0 and got.get("serial") == "036", f"exit {code}, {got}")
    check("firmware=2.10 is the text '2.10'", got.get("firmware") == "2.10", repr(got.get("firmware")))
    check("remote=on is the text 'on'", got.get("remote") == "on", repr(got.get("remote")))
    check("notes with a colon is that text", got.get("notes") == "moved 20 m: east", repr(got.get("notes")))
    code, out = run(script, path, "S03", "notes=yes")
    got = entry(path, "S03").get("notes")
    check("notes=yes is the text 'yes'", code == 0 and got == "yes", f"exit {code}, {got!r}")
    code, out = run(script, path, "S01", "notes=# taped")
    got = entry(path, "S01")
    check("notes=# taped writes that text, not a removal", code == 0 and got.get("notes") == "# taped",
          f"exit {code}, {got}")


def test_types(script) -> None:
    path = put("types")
    code, out = run(script, path, "S02", "dipole_length_ex=52", "swap_h=true", "flip_h=[hy]")
    got = entry(path, "S02")
    value = got.get("dipole_length_ex")
    check("dipole_length_ex=52 is the number 52.0", code == 0 and type(value) is float and value == 52.0,
          f"exit {code}, {value!r}")
    check("swap_h=true is the bool True", got.get("swap_h") is True, repr(got.get("swap_h")))
    check("flip_h=[hy] is the list [hy]", got.get("flip_h") == ["hy"], repr(got.get("flip_h")))


def test_refused(script) -> None:
    for arg in ("rot_h=abc", "dipole_length_ex=abc", "flip_h=hy", "channels=ex", "swap_h=1", "bogus_key=1",
                "bogus_key="):
        path = put("refused")
        key = arg.partition("=")[0]
        code, out = run(script, path, "S02", arg)
        check(f"{arg} refused with exit 2, the file untouched, {key} named",
              code == 2 and untouched(path) and key in out, f"exit {code}, {out.strip()[:200]}")


def test_messages(script) -> None:
    for args, fragment in ((["dipole_length_ex=50", "m"], "put quotes around a value with a space"),
                           (["dipole_length=46"], "the closest keys are dipole_length_e"),
                           (["dipole_length_ex=50m"], "type the number alone, with no unit")):
        path = put("messages")
        code, out = run(script, path, "S02", *args)
        check(f"{' '.join(args)}: refused with exit 2 and what to type", code == 2 and untouched(path)
              and fragment in out, f"exit {code}, {out.strip()[:200]}")


def test_remove(script) -> None:
    path = put("remove")
    code, out = run(script, path, "S01", "notes=")
    got = entry(path, "S01")
    check("notes= removes the key", code == 0 and "notes" not in got, f"exit {code}, {got}")


def test_defaults(script) -> None:
    path = put("defaults_dry")
    code, out = run(script, path, "defaults", "azimuth_ey=91")
    lines = [line for line in out.splitlines() if "azimuth_ey" in line and "keep" in line]
    named = lines[0] if lines else ""
    check("defaults without --yes: exit 0 and nothing written", code == 0 and untouched(path), f"exit {code}")
    check("defaults without --yes names the sites that keep 90 (S02, S03, not S01)",
          "S02" in named and "S03" in named and "S01" not in named and "90" in named, out.strip()[:300])

    path = put("defaults_yes")
    code, out = run(script, path, "defaults", "azimuth_ey=91", "--yes")
    config = parsed(path)
    sites = config["sites"]
    check("defaults --yes writes 91 into defaults:", code == 0 and config["defaults"].get("azimuth_ey") == 91.0,
          f"exit {code}, {config.get('defaults')}")
    check("defaults --yes pins 90 into S02 and S03, S01 keeps 95",
          sites["S02"].get("azimuth_ey") == 90.0 and sites["S03"].get("azimuth_ey") == 90.0
          and sites["S01"].get("azimuth_ey") == 95.0, str(sites))
    azimuths = {name: site(path, name).azimuth_ey for name in ("S01", "S02", "S03")}
    check("Survey.site reads the same azimuths after the change", azimuths == {"S01": 95.0, "S02": 90.0,
                                                                                "S03": 90.0}, str(azimuths))
    previous = path.with_name("survey.yaml.previous")
    check("survey.yaml.previous holds the old bytes and is printed",
          previous.exists() and previous.read_bytes() == TEXT.encode("utf-8") and "survey.yaml.previous" in out,
          out.strip()[-200:])


def test_add(script) -> None:
    root = SCRATCH / "raw"
    shutil.rmtree(root, ignore_errors=True)
    (root / "S04").mkdir(parents=True)
    text = TEXT.replace("data_root: X\n", f"data_root: {root.as_posix()}\n")
    path = put("add", text)
    code, out = run(script, path, "S04", "latitude=-31.3", "--add")
    got = parsed(path)["sites"]
    check("--add S04, a folder under data_root, adds the entry", text != TEXT and code == 0
          and got.get("S04") == {"latitude": -31.3}, f"exit {code}, {out}")
    path = put("add_no_folder", text)
    code, out = run(script, path, "S05", "latitude=-31.3", "--add")
    looked = str(root / "S05")
    check("--add S05, no folder under data_root: refused with exit 2, the file untouched, the folder named",
          code == 2 and path.read_bytes() == text.encode("utf-8")
          and not path.with_name("survey.yaml.previous").exists() and looked in out
          and "derived_from= or bursts_of=" in out, f"exit {code}, looked for {looked}, {out.strip()}")
    for name, key, rate in (("S02L", "derived_from", "1.0"), ("S02H", "bursts_of", "24000")):
        path = put("add_no_folder_by_design", text)
        code, out = run(script, path, name, f"{key}=S02", f"sample_rate={rate}", "--add")
        got = parsed(path)["sites"].get(name)
        check(f"--add {name} {key}=S02, no folder by design, adds the entry",
              code == 0 and got == {key: "S02", "sample_rate": float(rate)}, f"exit {code}, {got}, {out.strip()}")
    path = put("no_entry")
    code, out = run(script, path, "S09", "latitude=1.0")
    check("a site with no entry is refused without --add", code == 2 and untouched(path) and "S09" in out,
          f"exit {code}, {out.strip()}")


def test_nothing(script) -> None:
    path = put("nothing")
    code, out = run(script, path, "S02", "latitude=-31.1")
    check("a request that changes nothing: exit 0, bytes and no copy", code == 0 and untouched(path),
          f"exit {code}, {out.strip()}")


def test_command() -> None:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO / "src"), os.environ.get("PYTHONPATH", "")])}
    path = put("command")
    done = subprocess.run([sys.executable, str(SCRIPT), str(path), "S02", "rot_h=abc"], capture_output=True,
                          text=True, env=env, cwd=REPO)
    check("command line: a refused value exits 2", done.returncode == 2 and untouched(path),
          f"exit {done.returncode}, {done.stderr.strip()[-200:]}")
    done = subprocess.run([sys.executable, str(SCRIPT), str(path), "S02", "rot_h=3.5"], capture_output=True,
                          text=True, env=env, cwd=REPO)
    check("command line: a written value exits 0", done.returncode == 0 and entry(path, "S02").get("rot_h") == 3.5,
          f"exit {done.returncode}, {done.stdout.strip()[-200:]} {done.stderr.strip()[-200:]}")


def main() -> int:
    logger.remove()
    print(__doc__.split("**This test fails if**")[1].split("The mutation")[0].strip())
    print()
    script = load_script()
    tests = [(test_text, script), (test_types, script), (test_refused, script), (test_messages, script),
             (test_remove, script),
             (test_defaults, script), (test_add, script), (test_nothing, script), (test_command,)]
    for test, *args in tests:
        print(f"{test.__name__}:")
        try:
            test(*args)
        except Exception as exc:  # a crash of the script is a failure of the criterion under test
            check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print(f"\n{'FAIL' if failed else 'PASS'}  survey_set_unit ({len(failed)} of {n_checks} checks failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
