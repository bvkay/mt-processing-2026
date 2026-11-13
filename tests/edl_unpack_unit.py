# -*- coding: utf-8 -*-
"""
Unit test for scripts/edl_unpack.py

Builds a synthetic PR6-24 site zip in a fresh scratch folder and unpacks it
with the script's `main`. The zip holds the station TST01's own files in two
day folders (two hours of the five channels, TP and ambientTemperature, and
the day logs), one hour written without the "_" before the stamp, an hour
after the window, a file stamped 2003-01-01 before the GPS locked with its
day log, another station's files (OTH9), a ``$RECYCLE.BIN`` with a
recorder.ini naming another station (OLD5_) beside a recycled day folder of
OLD5's files and a recorder.msg, the deployment's ``config/recorder.ini``
(TST01_) and ``log/recorder.msg``, a chkdsk ``FOUND.000/FILE0001.CHK``, the
logger's ``temp/cr00``, a field-sheet docx and folder entries. A second and
a third zip test the name clash in the site folder and the salvage tree's
shared station folders.

Usage:
    python tests/edl_unpack_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

(1) the site folder's file set differs from the expected one: the own
    station's channel, TP and ambientTemperature files in the window (the
    station given as "tst01_" matches the files' "TST01_" and "TST01"), the
    day logs of the two kept days, and the deployment's recorder.ini and
    recorder.msg; in particular if the recycle bin's recorder.ini, another
    station's file, the 2003 file or the hour after the window is in it;
(2) a manifest's row count differs from the zip's member count, a member is
    listed twice, a non-folder row has no destination or a destination that
    does not exist, or the destinations' byte total differs from the zip's
    uncompressed total;
(3) the other station's file is not at ``<salvage>/OTH9/<name>``, the 2003
    file and the hour after the window are not under ``_unsynced/TST01/``,
    the recycled OLD5 files and the bin's recorder.ini and recorder.msg are
    not under ``_recycle_bin/<zip>/OLD5/``, the CHK fragment is not under
    ``_found000/<zip>/``, temp/cr00 is not under ``_other/<zip>/temp/``, or
    the docx is not under ``<records>/field_sheets/TST01/``;
(4) a copied file differs from its member, or a site channel file's
    `samples` differs from the lines written into it;
(5) a zip with the same file name in two folders is not refused (exit 3)
    before anything is copied, or the same zip with ``--exclude`` on one
    folder does not unpack with that copy under ``_other/``;
(6) a second zip with an identical OTH9 file does not reuse it (no copy, a
    note) or a different OTH9 file of the same name is not kept as
    ``<stem>__<zip folder><ext>``;
(7) a second run into the existing site folder without --force does not
    exit 2, a --dry-run copies anything or writes the real manifest name, or
    a free-space floor above the drive's free space does not stop the run
    (exit 2) before copying;
(8) with the window set to the whole of 2016 and ``--day-logs window``, the
    hour after the narrow window, its day log and the day log of a day
    without channel files are not kept in the site folder (that last one
    under the reason "own day log in the window"; in the narrow run it is
    under ``_unsynced/TST01/``), or the 2003 file and its day log leave
    ``_unsynced/TST01/``.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
from _scratch import scratch_dir  # noqa: E402

SCRIPT = REPO / "scripts" / "edl_unpack.py"
spec = importlib.util.spec_from_file_location("edl_unpack", SCRIPT)
edl_unpack = importlib.util.module_from_spec(spec)
sys.modules["edl_unpack"] = edl_unpack  # dataclasses look the module up by name
spec.loader.exec_module(edl_unpack)

INI = "[recorder]\nstation_long_identifier = {}\nchannel_0_samplerate = 10\nchannel_1_samplerate = 10\n"
WINDOW = ["--start", "2016-01-22T00:00:00Z", "--end", "2016-01-23T12:00:00Z"]


def channel_text(n: int, seed: int) -> bytes:
    """Return an ASCII channel file of n samples."""
    return "".join(f"{(seed * 7 + i) % 1000 - 500}\n" for i in range(n)).encode()


def docx_bytes() -> bytes:
    """Return a minimal docx (a zip with word/document.xml)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:t>SITE NAME</w:t></w:document>")
    return buf.getvalue()


def own_hour(members: dict, folder: str, stamp: str, sep: str = "_", n: int = 50) -> list[str]:
    """Add one hour of TST01's seven files; return their names."""
    names = []
    for k, ext in enumerate(("BX", "BY", "BZ", "EX", "EY", "TP", "ambientTemperature")):
        name = f"TST01{sep}{stamp}.{ext}"
        members[f"{folder}/{name}"] = channel_text(n + k, int(stamp[-6:-2]) + k)
        names.append(name)
    return names


def build_main_zip(path: Path) -> tuple[set, dict]:
    """Write the main synthetic zip; return the expected site-folder names and the members."""
    m: dict[str, bytes] = {}
    expected = set()
    expected |= set(own_hour(m, "022", "160122100000"))
    expected |= set(own_hour(m, "023", "160123050000", sep=""))
    for day, folder in (("160122", "022"), ("160123", "023")):
        for ext in ("gps", "gst", "pll", "msg"):
            m[f"{folder}/TST01_{day}000000.{ext}"] = f"{ext} of {day}\n".encode()
            expected.add(f"TST01_{day}000000.{ext}")
    own_hour(m, "024", "160124100000")  # after the window
    m["024/TST01_160124000000.gps"] = b">RPV00016-4094613+1449183600000012;*70<\n"
    m["025/TST01_160125000000.gps"] = b"a day log of a day without channel files\n"
    m["001/TST01_030101000140.EX"] = channel_text(20, 3)
    m["001/TST01_030101000000.gps"] = b"unsynced\n"
    m["319/OTH9_151115183118.EX"] = channel_text(30, 9)
    m["319/OTH9_151115000000.gps"] = b"other\n"
    m["$RECYCLE.BIN/$RAB12CD/recorder.ini"] = INI.format("OLD5_").encode()
    m["$RECYCLE.BIN/$RAB12CE/recorder.msg"] = b"old log\n"
    m["$RECYCLE.BIN/$RAB12CF/OLD5_150101000000.BX"] = channel_text(10, 5)
    m["$RECYCLE.BIN/$IAB12CD"] = b"\x02\x00metadata"
    m["config/recorder.ini"] = INI.format("TST01_").encode()
    m["log/recorder.msg"] = b"Serial no 12345\n"
    expected |= {"recorder.ini", "recorder.msg"}
    m["FOUND.000/FILE0001.CHK"] = b"\x00" * 64
    m["temp/cr00"] = b"\x01" * 16
    m["site_t01.docx"] = docx_bytes()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for folder in ("022/", "023/", "config/"):
            z.writestr(folder, b"")
        for name, data in m.items():
            z.writestr(name, data)
    return expected, m


def run(zip_path: Path, out_root: Path, records: Path, salvage: Path, *extra) -> int:
    """Run the script's main on one zip as site TST01."""
    return edl_unpack.main([str(zip_path), "TST01", str(out_root), "--station", "tst01_", *WINDOW,
                            "--records", str(records), "--salvage-root", str(salvage), *extra])


def manifest(records: Path, site: str = "TST01", tag: str = "") -> list[dict]:
    """Read a manifest CSV."""
    with open(records / "manifests" / f"{site}_manifest{tag}.csv", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check_accounting(zip_path: Path, rows: list[dict]) -> None:
    """Criterion (2) on one zip and its manifest."""
    with zipfile.ZipFile(zip_path) as z:
        infos = z.infolist()
    assert len(rows) == len(infos), (len(rows), len(infos))
    assert sorted(r["member"] for r in rows) == sorted(i.filename for i in infos), "a member missing or twice"
    total = 0
    for r in rows:
        if r["action"] == "directory":
            assert r["member"].endswith("/") and int(r["bytes"]) == 0, r
            continue
        dest = Path(r["destination"])
        assert r["destination"] and dest.is_file(), f"no destination on disk for {r['member']}: {r['destination']!r}"
        assert dest.stat().st_size == int(r["bytes"]), (r["member"], dest.stat().st_size, r["bytes"])
        total += dest.stat().st_size
    assert total == sum(i.file_size for i in infos), (total, sum(i.file_size for i in infos))


def main() -> None:
    root = Path(tempfile.mkdtemp(dir=scratch_dir("edl_unpack_unit")))
    out_root, records, salvage = root / "survey", root / "records", root / "salvage"
    zip_path = root / "zips" / "site_t01.zip"
    zip_path.parent.mkdir(parents=True)
    expected, members = build_main_zip(zip_path)

    # (7) dry run first: nothing copied, the dry-run names only
    assert run(zip_path, out_root, records, salvage, "--dry-run") == 0
    assert not (out_root / "TST01").exists() and not salvage.exists(), "the dry run copied files"
    assert (records / "manifests" / "TST01_manifest.dryrun.csv").is_file()
    assert not (records / "manifests" / "TST01_manifest.csv").exists()
    # (7) a floor above the free space stops the run before copying
    assert run(zip_path, out_root, records, salvage, "--min-free-gb", "1e9") == 2
    assert not (out_root / "TST01").exists(), "copied in spite of the free-space floor"

    assert run(zip_path, out_root, records, salvage) == 0
    site = out_root / "TST01"
    got = {p.name for p in site.iterdir()}
    # (1)
    assert got == expected, f"site folder differs: extra {sorted(got - expected)}, missing {sorted(expected - got)}"
    assert "TST01" in (site / "recorder.ini").read_text() and "OLD5" not in (site / "recorder.ini").read_text()
    print(f"  (1) site folder: {len(got)} files, the expected set; recorder.ini names TST01_")
    rows = manifest(records)
    check_accounting(zip_path, rows)
    print(f"  (2) manifest: {len(rows)} rows = members, every destination on disk, byte totals equal")
    # (3)
    wants = {
        "319/OTH9_151115183118.EX": salvage / "OTH9" / "OTH9_151115183118.EX",
        "001/TST01_030101000140.EX": salvage / "_unsynced" / "TST01" / "TST01_030101000140.EX",
        "001/TST01_030101000000.gps": salvage / "_unsynced" / "TST01" / "TST01_030101000000.gps",
        "024/TST01_160124100000.EX": salvage / "_unsynced" / "TST01" / "TST01_160124100000.EX",
        "024/TST01_160124000000.gps": salvage / "_unsynced" / "TST01" / "TST01_160124000000.gps",
        "$RECYCLE.BIN/$RAB12CF/OLD5_150101000000.BX": salvage / "_recycle_bin" / "site_t01" / "OLD5" / "OLD5_150101000000.BX",
        "$RECYCLE.BIN/$RAB12CD/recorder.ini": salvage / "_recycle_bin" / "site_t01" / "OLD5" / "recorder.ini",
        "$RECYCLE.BIN/$RAB12CE/recorder.msg": salvage / "_recycle_bin" / "site_t01" / "OLD5" / "recorder.msg",
        "FOUND.000/FILE0001.CHK": salvage / "_found000" / "site_t01" / "FILE0001.CHK",
        "temp/cr00": salvage / "_other" / "site_t01" / "temp" / "cr00",
        "site_t01.docx": records / "field_sheets" / "TST01" / "site_t01.docx",
    }
    by_member = {r["member"]: r for r in rows}
    for member, path in wants.items():
        assert Path(by_member[member]["destination"]) == path, (member, by_member[member]["destination"], path)
        assert path.is_file(), path
    print(f"  (3) {len(wants)} salvage and records destinations as expected")
    # (4)
    for member, data in members.items():
        assert Path(by_member[member]["destination"]).read_bytes() == data, f"copy differs: {member}"
    counted = [r for r in rows if r["action"] == "kept" and r["samples"]]
    for r in counted:
        assert int(r["samples"]) == members[r["member"]].count(b"\n"), r
    assert len(counted) == 14, len(counted)
    summary = json.loads((records / "manifests" / "TST01_summary.json").read_text())
    assert summary["kept_stamps_all_five"] == 2 and summary["kept_hours_all_five"] == 2, summary
    print(f"  (4) every copy equals its member; samples of {len(counted)} site files equal their lines")
    # (7) no second run without --force
    assert run(zip_path, out_root, records, salvage) == 2
    print("  (7) dry run copies nothing; free-space floor and existing site folder refused (exit 2)")

    # (5) a name clash in the site folder
    clash = root / "zips" / "site_t02.zip"
    with zipfile.ZipFile(clash, "w") as z:
        z.writestr("022/TST01_160122100000.EX", channel_text(50, 1))
        z.writestr("rr/TST01_160122100000.EX", channel_text(50, 1))
    out2 = root / "survey2"
    assert run(clash, out2, records, salvage) == 3, "the name clash was not refused"
    assert not out2.exists(), "files copied before the clash was refused"
    assert run(clash, out2, records, salvage, "--exclude", "rr/*") == 0
    rows2 = manifest(records)
    check_accounting(clash, rows2)
    assert Path({r["member"]: r for r in rows2}["rr/TST01_160122100000.EX"]["destination"]) == \
        salvage / "_other" / "site_t02" / "rr" / "TST01_160122100000.EX"
    print("  (5) a clash in the site folder is refused (exit 3) with nothing copied; --exclude sets the copy aside")

    # (6) the salvage tree's shared station folder
    third = root / "zips" / "site_t03.zip"
    with zipfile.ZipFile(third, "w") as z:
        z.writestr("319/OTH9_151115183118.EX", members["319/OTH9_151115183118.EX"])
        z.writestr("319/OTH9_151115000000.gps", b"another day log\n")
    out3 = root / "survey3"
    assert run(third, out3, records, salvage) == 0
    rows3 = {r["member"]: r for r in manifest(records)}
    same = rows3["319/OTH9_151115183118.EX"]
    assert Path(same["destination"]) == salvage / "OTH9" / "OTH9_151115183118.EX" and "identical" in same["note"], same
    other = rows3["319/OTH9_151115000000.gps"]
    assert Path(other["destination"]) == salvage / "OTH9" / "OTH9_151115000000__site_t03.gps", other
    assert (salvage / "OTH9" / "OTH9_151115000000.gps").read_bytes() == b"other\n"
    check_accounting(third, list(rows3.values()))
    print("  (6) identical salvage file reused with a note; a different one kept as <stem>__site_t03<ext>")
    # (8) every own stamp of 2016 kept, day logs by the window
    out4, rec4 = root / "survey4", root / "records4"
    assert edl_unpack.main([str(zip_path), "TST01", str(out4), "--station", "TST01", "--start", "2016-01-01T00:00:00Z",
                            "--end", "2016-12-31T23:59:59Z", "--day-logs", "window", "--records", str(rec4),
                            "--salvage-root", str(salvage)]) == 0
    got4 = {p.name for p in (out4 / "TST01").iterdir()}
    later = {"TST01_160124100000.EX", "TST01_160124000000.gps", "TST01_160125000000.gps"}
    assert later <= got4, sorted(later - got4)
    assert not {"TST01_030101000140.EX", "TST01_030101000000.gps"} & got4, "a 2003 file reached the site folder"
    rows4 = {r["member"]: r for r in manifest(rec4)}
    assert rows4["025/TST01_160125000000.gps"]["reason"] == "own day log in the window", rows4["025/TST01_160125000000.gps"]
    assert Path(by_member["025/TST01_160125000000.gps"]["destination"]).parent == salvage / "_unsynced" / "TST01"
    assert Path(rows4["001/TST01_030101000140.EX"]["destination"]) == salvage / "_unsynced" / "TST01" / "TST01_030101000140.EX"
    check_accounting(zip_path, list(rows4.values()))
    print(f"  (8) whole-2016 window with --day-logs window: {len(got4)} files kept, the 2003 files stay in _unsynced")
    print(f"  scratch: {root}")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    main()
    print("\nPASS  edl_unpack_unit")
