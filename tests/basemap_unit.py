"""Unit test for `scripts/fetch_basemap.py`, with the network mocked: no tile is fetched.

    python tests/basemap_unit.py

`contextily.bounds2img` is replaced by a function that records what it was
asked for and returns a synthetic 256 x 256 Web Mercator mosaic whose green
value is the pixel's source row and whose red value is its source column,
over a Mercator extent a degree wider than asked on every side, computed
here with pyproj (EPSG:4326 -> EPSG:3857) rather than the script's formula.

**This test fails if** (1) for a synthetic survey whose sites span 10 S to
60 S -- wide enough that a warp linear in latitude would put the middle row
more than 3 source rows away from the Mercator one (checked, so the test can
tell them apart) -- the warped `basemap.png`, at the latitudes of the centres
of its rows 10 %, 50 % and 90 % of the way down, does not hold in every
column the source row at the pyproj Mercator y of that latitude (to within
the 0.5 of the rounding to uint8), or at three longitudes the source column
at their Mercator x; (2) `basemap.json`'s lon_min, lon_max, lat_min, lat_max
do not equal (1e-9) the sites' extent computed here from the YAML, padded on
each side by max(0.15 x span, 0.1 deg) -- for that survey and for a copy of
the curnamona survey -- or bounds2img was not asked, with ll=True, for exactly
that extent from OpenTopoMap; its width and height are not the PNG's, the
PNG is not RGB, or the zoom is not what bounds2img was asked for: with
`--zoom auto`, min(ceil(log2(720 / span))) over the two spans computed here,
with `--zoom 9`, 9; (3) a bounds2img that raises (no network) does not make
the script return 1 with "needs internet" on stderr and leave no basemap file
behind. Everything is written under the scratch directory.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import shutil
import sys
from pathlib import Path

import contextily
import numpy as np
import yaml
from PIL import Image
from pyproj import Transformer

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "fetch_basemap.py"
CURNAMONA = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
SCRATCH = Path(
    r"C:\Users\joint\AppData\Local\Temp\claude\D--BEN-BBMT-Processing-2026"
    r"\7432a3ce-c47b-448e-8958-b1c946ec7c08\scratchpad\basemap_unit"
)
SIZE = 256  # the synthetic mosaic's rows and columns: each fits a uint8
MOSAIC_PAD_DEG = 1.0  # whole tiles cover more than was asked for
TO_MERCATOR = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
TO_LONLAT = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
WIDE_SITES = {"S10": (-10.0, 120.0), "S35": (-35.0, 133.0), "S60": (-60.0, 150.0)}

CALLS: list[dict] = []


def load_script():
    spec = importlib.util.spec_from_file_location("fetch_basemap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_bounds2img(w, s, e, n, zoom="auto", source=None, ll=False, **kwargs):
    """A mosaic over the request plus a degree each side: green = source row, red = source column."""
    CALLS.append({"w": w, "s": s, "e": e, "n": n, "zoom": zoom, "source": source, "ll": ll})
    left, bottom = TO_MERCATOR.transform(w - MOSAIC_PAD_DEG, s - MOSAIC_PAD_DEG)
    right, top = TO_MERCATOR.transform(e + MOSAIC_PAD_DEG, n + MOSAIC_PAD_DEG)
    img = np.zeros((SIZE, SIZE, 4), np.uint8)
    img[..., 0] = np.arange(SIZE)[None, :]
    img[..., 1] = np.arange(SIZE)[:, None]
    img[..., 3] = 255
    return img, (left, right, bottom, top)


def offline_bounds2img(*args, **kwargs):
    import requests

    raise requests.ConnectionError("no route to tile.opentopomap.org (mocked)")


def write_survey(name: str, sites: dict | None = None) -> Path:
    """A survey.yaml under the scratch directory with its workspace there too."""
    folder = SCRATCH / name
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    if sites is None:
        config = yaml.safe_load(CURNAMONA.read_text(encoding="utf-8"))
    else:
        config = {"name": name, "data_root": str(folder / "raw"),
                  "sites": {k: {"latitude": lat, "longitude": lon} for k, (lat, lon) in sites.items()}}
    config["workspace"] = str(folder / "work")
    path = folder / "survey.yaml"
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def expected_extent(survey_yaml: Path) -> tuple[float, float, float, float]:
    """From the YAML itself: the sites' extent padded by max(0.15 x span, 0.1 deg) per side."""
    sites = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))["sites"]
    lons = [v["longitude"] for v in sites.values() if v.get("latitude") is not None and v.get("longitude") is not None]
    lats = [v["latitude"] for v in sites.values() if v.get("latitude") is not None and v.get("longitude") is not None]
    pad_x = max(0.15 * (max(lons) - min(lons)), 0.1)
    pad_y = max(0.15 * (max(lats) - min(lats)), 0.1)
    return min(lons) - pad_x, min(lats) - pad_y, max(lons) + pad_x, max(lats) + pad_y


def run(script, survey_yaml: Path, *options: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = script.main([str(survey_yaml), *options])
    return code, out.getvalue(), err.getvalue()


def check_extent_and_meta(survey_yaml: Path, stdout: str, want_zoom: int) -> tuple[dict, np.ndarray]:
    work = survey_yaml.parent / "work"
    meta = json.loads((work / "basemap.json").read_text(encoding="utf-8"))
    png = Image.open(work / "basemap.png")
    assert png.mode == "RGB", png.mode
    rgb = np.asarray(png)
    w, s, e, n = expected_extent(survey_yaml)
    got = (meta["lon_min"], meta["lat_min"], meta["lon_max"], meta["lat_max"])
    assert np.allclose(got, (w, s, e, n), rtol=0, atol=1e-9), (got, (w, s, e, n))
    call = CALLS[-1]
    assert call["ll"] is True and np.allclose((call["w"], call["s"], call["e"], call["n"]), (w, s, e, n),
                                              rtol=0, atol=1e-9), call
    assert call["source"].name == "OpenTopoMap" and meta["provider"] == "OpenTopoMap", (call, meta)
    assert "OpenTopoMap" in meta["attribution"], meta["attribution"]
    assert call["zoom"] == meta["zoom"] == want_zoom, (call["zoom"], meta["zoom"], want_zoom)
    assert (meta["width"], meta["height"]) == png.size, (meta, png.size)
    assert f"basemap: OpenTopoMap zoom {want_zoom}, {png.size[0]}x{png.size[1]} px" in stdout, stdout
    return meta, rgb


def auto_zoom_here(survey_yaml: Path) -> int:
    w, s, e, n = expected_extent(survey_yaml)
    zoom = min(math.ceil(math.log2(720.0 / (e - w))), math.ceil(math.log2(720.0 / (n - s))))
    return max(0, min(zoom, 17))  # OpenTopoMap's zoom range


def test_rows_follow_mercator(script) -> None:
    survey_yaml = write_survey("wide", WIDE_SITES)
    code, stdout, stderr = run(script, survey_yaml)
    assert code == 0, (code, stdout, stderr)
    meta, rgb = check_extent_and_meta(survey_yaml, stdout, auto_zoom_here(survey_yaml))
    w, s, e, n = expected_extent(survey_yaml)
    left, bottom = TO_MERCATOR.transform(w - MOSAIC_PAD_DEG, s - MOSAIC_PAD_DEG)
    right, top = TO_MERCATOR.transform(e + MOSAIC_PAD_DEG, n + MOSAIC_PAD_DEG)
    dx, dy = (right - left) / SIZE, (top - bottom) / SIZE
    height, width = rgb.shape[:2]
    lat_top, lat_bottom = n + MOSAIC_PAD_DEG, s - MOSAIC_PAD_DEG
    for fraction in (0.1, 0.5, 0.9):
        r = int(fraction * height)
        lat = n - (r + 0.5) * (n - s) / height
        want = (top - TO_MERCATOR.transform(0.0, lat)[1]) / dy - 0.5
        linear = (lat_top - lat) / (lat_top - lat_bottom) * SIZE - 0.5
        if fraction == 0.5:
            assert abs(want - linear) > 3, f"a linear warp would be only {abs(want - linear):.2f} rows off"
        got = rgb[r, :, 1].astype(float)
        assert np.all(np.abs(got - want) <= 0.5 + 1e-9), (lat, want, got.min(), got.max())
        c = int(fraction * width)
        lon = w + (c + 0.5) * (e - w) / width
        want_col = (TO_MERCATOR.transform(lon, 0.0)[0] - left) / dx - 0.5
        got_col = rgb[:, c, 0].astype(float)
        assert np.all(np.abs(got_col - want_col) <= 0.5 + 1e-9), (lon, want_col, got_col.min(), got_col.max())
        print(f"  lat {lat:8.3f}: row {r:3d} holds source row {got[0]:.0f} (Mercator {want:.2f}; "
              f"linear in latitude would be {linear:.2f}); lon {lon:8.3f}: column {c} holds "
              f"source column {got_col[0]:.0f} ({want_col:.2f})")
    print(f"  wide survey: {width}x{height} px, extent {meta['lon_min']:.3f}..{meta['lon_max']:.3f}, "
          f"{meta['lat_min']:.3f}..{meta['lat_max']:.3f} = the padded site extent, zoom {meta['zoom']} (auto)")


def test_curnamona_extent(script) -> None:
    survey_yaml = write_survey("curnamona")
    code, stdout, stderr = run(script, survey_yaml, "--zoom", "9")
    assert code == 0, (code, stdout, stderr)
    meta, rgb = check_extent_and_meta(survey_yaml, stdout, 9)
    print(f"  curnamona copy, --zoom 9: lon {meta['lon_min']:.4f}..{meta['lon_max']:.4f}, "
          f"lat {meta['lat_min']:.4f}..{meta['lat_max']:.4f} = the padded site extent; "
          f"{rgb.shape[1]}x{rgb.shape[0]} px RGB")


def test_offline_says_so(script) -> None:
    survey_yaml = write_survey("offline", WIDE_SITES)
    contextily.bounds2img = offline_bounds2img
    try:
        code, stdout, stderr = run(script, survey_yaml)
    finally:
        contextily.bounds2img = fake_bounds2img
    work = survey_yaml.parent / "work"
    left = sorted(p.name for p in work.glob("basemap.*")) if work.exists() else []
    assert code == 1 and "needs internet" in stderr and not left, (code, stderr, left)
    print(f"  offline: exit {code}, {stderr.strip().splitlines()[-1]!r}, no basemap file written")


if __name__ == "__main__":
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    real = contextily.bounds2img
    contextily.bounds2img = fake_bounds2img
    try:
        script = load_script()
        tests = [test_rows_follow_mercator, test_curnamona_extent, test_offline_says_so]
        for test in tests:
            test(script)
            print(f"  ok  {test.__name__}")
    finally:
        contextily.bounds2img = real
    print(f"\nPASS  basemap_unit ({len(tests)} tests, {len(CALLS)} mocked fetches, no network)")
