# -*- coding: utf-8 -*-
"""
Unit test for scripts/fetch_basemap.py

Runs the script with the network mocked. `contextily.bounds2img` is replaced
by a function that records the request and returns a synthetic 256 x 256 Web
Mercator mosaic whose green value is the pixel's source row and whose red
value is its source column. The mosaic covers a Mercator extent a degree
wider than requested on every side, computed with pyproj (EPSG:4326 ->
EPSG:3857) independently of the script's formula. Everything is written
under the scratch directory.

Usage:
    python tests/basemap_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if** (1) for a synthetic survey whose sites span 10 S to
60 S -- wide enough that a warp linear in latitude would put the middle row
more than 3 source rows away from the Mercator one (checked, so the test can
tell them apart) -- the warped `basemap.png`, at the latitudes of the centres
of its rows 10 %, 50 % and 90 % of the way down, does not hold in every
column the source row at the pyproj Mercator y of that latitude (to within
the 0.5 of the rounding to uint8), or at three longitudes the source column
at their Mercator x; (2) `basemap.json`'s lon_min, lon_max, lat_min, lat_max
do not equal (1e-9) the sites' extent computed here from the YAML, padded on
each side by max(0.15 x span, 0.1 deg) -- for that survey, a copy of the
curnamona survey and a one-site survey -- or bounds2img was not asked, with
ll=True, for exactly that extent from Esri.WorldImagery (the default: imagery,
no place names) or, when --provider names one, from that provider, with its
attribution in the JSON; its width and height are not the PNG's or the PNG is
not RGB; (3) the zoom is not what bounds2img was asked for and the JSON
records: with `--zoom auto`, three levels finer than min(ceil(log2(720 /
span))) over the two spans, coarsened one level at a time (never below that
base) into the provider's zoom range (19 when xyzservices gives none) and
until the image's longer side -- the extent's Mercator metres from pyproj
over the tile pixel's 2 pi 6378137 / (256 x 2^zoom) m -- is at most 8000 px,
all computed here; that rule must give 6 for the wide survey (its base 4 +
2: 7 would be 8194 px tall), 11 for curnamona (its base 8 + 3: 7222 px
tall), 6 for a survey from 55 S to 80 S (its base + 1: 7 would be 9714 px
tall), 15 for a one-site survey (its base 12 + 3) and 13 for that survey
from Esri.WorldShadedRelief (the provider's max_zoom), so every branch is taken;
with `--zoom 7`, 7; (4) a bounds2img that raises (no network) does not make
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

from _scratch import scratch_dir

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "fetch_basemap.py"
CURNAMONA = REPO / "surveys" / "curnamona_cube" / "survey.yaml"
SCRATCH = scratch_dir("basemap_unit")
SIZE = 256  # the synthetic mosaic's rows and columns: each fits a uint8
MOSAIC_PAD_DEG = 1.0  # whole tiles cover more than was asked for
TO_MERCATOR = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
TO_LONLAT = Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)
WIDE_SITES = {"S10": (-10.0, 120.0), "S35": (-35.0, 133.0), "S60": (-60.0, 150.0)}
ONE_SITE = {"T01": (-31.0, 138.6)}  # padded 0.1 deg each way: a 0.2 x 0.2 deg extent
POLAR_SITES = {"P55": (-55.0, 140.0), "P80": (-80.0, 141.0)}  # Mercator stretches it tall
DEFAULT_PROVIDER = "Esri.WorldImagery"
MAX_ZOOM = {"Esri.WorldImagery": 19, "Esri.WorldShadedRelief": 13}  # xyzservices gives none for the first
MAX_SIDE_PX, FINER = 8000, 3

CALLS: list[dict] = []


def load_script():
    """Import scripts/fetch_basemap.py as a module."""
    spec = importlib.util.spec_from_file_location("fetch_basemap", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_bounds2img(w, s, e, n, zoom="auto", source=None, ll=False, **kwargs):
    """Record a bounds2img request and return a synthetic mosaic.

    The mosaic covers the request plus a degree on each side, with green =
    source row and red = source column.

    Returns:
        tuple[np.ndarray, tuple]: RGBA mosaic and its Mercator
        (left, right, bottom, top) in metres.
    """
    CALLS.append({"w": w, "s": s, "e": e, "n": n, "zoom": zoom, "source": source, "ll": ll})
    left, bottom = TO_MERCATOR.transform(w - MOSAIC_PAD_DEG, s - MOSAIC_PAD_DEG)
    right, top = TO_MERCATOR.transform(e + MOSAIC_PAD_DEG, n + MOSAIC_PAD_DEG)
    img = np.zeros((SIZE, SIZE, 4), np.uint8)
    img[..., 0] = np.arange(SIZE)[None, :]
    img[..., 1] = np.arange(SIZE)[:, None]
    img[..., 3] = 255
    return img, (left, right, bottom, top)


def offline_bounds2img(*args, **kwargs):
    """Stand-in for bounds2img without network: raises requests.ConnectionError."""
    import requests

    raise requests.ConnectionError("no route to server.arcgisonline.com (mocked)")


def write_survey(name: str, sites: dict | None = None) -> Path:
    """Write a survey.yaml, with its workspace, under the scratch directory.

    Args:
        name (str): Survey and folder name.
        sites (dict | None): Site name to (latitude, longitude); None copies
            the curnamona survey.

    Returns:
        Path: The survey.yaml written.
    """
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
    """Compute the expected extent from the YAML.

    Returns:
        tuple[float, float, float, float]: (west, south, east, north) of the
        sites, padded by max(0.15 x span, 0.1 deg) on each side.
    """
    sites = yaml.safe_load(survey_yaml.read_text(encoding="utf-8"))["sites"]
    lons = [v["longitude"] for v in sites.values() if v.get("latitude") is not None and v.get("longitude") is not None]
    lats = [v["latitude"] for v in sites.values() if v.get("latitude") is not None and v.get("longitude") is not None]
    pad_x = max(0.15 * (max(lons) - min(lons)), 0.1)
    pad_y = max(0.15 * (max(lats) - min(lats)), 0.1)
    return min(lons) - pad_x, min(lats) - pad_y, max(lons) + pad_x, max(lats) + pad_y


def run(script, survey_yaml: Path, *options: str) -> tuple[int, str, str]:
    """Run the script's main and return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = script.main([str(survey_yaml), *options])
    return code, out.getvalue(), err.getvalue()


def check_extent_and_meta(survey_yaml: Path, stdout: str, want_zoom: int,
                          provider: str = DEFAULT_PROVIDER) -> tuple[dict, np.ndarray]:
    """Check basemap.json, basemap.png and the last bounds2img request.

    Args:
        survey_yaml (Path): The survey the script ran on.
        stdout (str): The script's stdout.
        want_zoom (int): Expected zoom.
        provider (str): Expected provider name.

    Returns:
        tuple[dict, np.ndarray]: The JSON metadata and the PNG as an array.
    """
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
    assert call["source"].name == provider and meta["provider"] == provider, (call["source"].name, meta)
    assert meta["attribution"].startswith("Tiles (C) Esri"), meta["attribution"]
    assert call["zoom"] == meta["zoom"] == want_zoom, (call["zoom"], meta["zoom"], want_zoom)
    assert (meta["width"], meta["height"]) == png.size, (meta, png.size)
    assert f"basemap: {provider} zoom {want_zoom}, {png.size[0]}x{png.size[1]} px" in stdout, stdout
    return meta, rgb


def longer_side_px(extent, zoom: int) -> float:
    """Return the image's longer side in px at `zoom`, from pyproj's Mercator metres."""
    w, s, e, n = extent
    left, bottom = TO_MERCATOR.transform(w, s)
    right, top = TO_MERCATOR.transform(e, n)
    pixel_m = 2 * math.pi * 6378137.0 / (256 * 2 ** zoom)
    return max(right - left, top - bottom) / pixel_m


def auto_zoom_here(survey_yaml: Path, provider: str = DEFAULT_PROVIDER) -> tuple[int, int]:
    """Compute the expected automatic zoom.

    Returns:
        tuple[int, int]: (base, zoom): contextily's rule, then base + 3
        coarsened into the provider's range and under 8000 px.
    """
    extent = w, s, e, n = expected_extent(survey_yaml)
    base = min(math.ceil(math.log2(720.0 / (e - w))), math.ceil(math.log2(720.0 / (n - s))))
    base = max(0, min(base, MAX_ZOOM[provider]))
    zoom = min(base + FINER, MAX_ZOOM[provider])
    while zoom > base and longer_side_px(extent, zoom) > MAX_SIDE_PX:
        zoom -= 1
    return base, zoom


def test_rows_follow_mercator(script) -> None:
    survey_yaml = write_survey("wide", WIDE_SITES)
    code, stdout, stderr = run(script, survey_yaml)
    assert code == 0, (code, stdout, stderr)
    base, zoom = auto_zoom_here(survey_yaml)
    assert (base, zoom) == (4, 6), f"wide: base {base}, zoom {zoom}; expected 4 and 6"
    meta, rgb = check_extent_and_meta(survey_yaml, stdout, zoom)
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
          f"{meta['lat_min']:.3f}..{meta['lat_max']:.3f} = the padded site extent, zoom {meta['zoom']} "
          f"(auto: base {base} + 1; {zoom + 1} would be {longer_side_px(expected_extent(survey_yaml), zoom + 1):.0f} px)")


def test_curnamona_extent(script) -> None:
    survey_yaml = write_survey("curnamona")
    code, stdout, stderr = run(script, survey_yaml)
    assert code == 0, (code, stdout, stderr)
    base, zoom = auto_zoom_here(survey_yaml)
    assert (base, zoom) == (8, 11), f"curnamona: base {base}, zoom {zoom}; expected 8 and 11"
    meta, rgb = check_extent_and_meta(survey_yaml, stdout, zoom)
    too_big = longer_side_px(expected_extent(survey_yaml), zoom + 1)
    print(f"  curnamona copy, auto: zoom {zoom} (base {base} + 1; {zoom + 1} would be {too_big:.0f} px), "
          f"lon {meta['lon_min']:.4f}..{meta['lon_max']:.4f}, lat {meta['lat_min']:.4f}..{meta['lat_max']:.4f} "
          f"= the padded site extent; {rgb.shape[1]}x{rgb.shape[0]} px RGB (mocked mosaic)")
    code, stdout, stderr = run(script, survey_yaml, "--zoom", "7")
    assert code == 0, (code, stdout, stderr)
    check_extent_and_meta(survey_yaml, stdout, 7)
    print("  curnamona copy, --zoom 7: asked for 7, recorded 7")


def test_zoom_rule(script) -> None:
    survey_yaml = write_survey("polar", POLAR_SITES)
    code, stdout, stderr = run(script, survey_yaml)
    assert code == 0, (code, stdout, stderr)
    base, zoom = auto_zoom_here(survey_yaml)
    assert (base, zoom) == (5, 6), f"55-80 S: base {base}, zoom {zoom}; expected 5 and 6"
    check_extent_and_meta(survey_yaml, stdout, zoom)
    too_big = longer_side_px(expected_extent(survey_yaml), zoom + 1)
    print(f"  55-80 S, auto: zoom {zoom} = its base + 1 ({zoom + 1} would be {too_big:.0f} px)")
    survey_yaml = write_survey("one_site", ONE_SITE)
    code, stdout, stderr = run(script, survey_yaml)
    assert code == 0, (code, stdout, stderr)
    base, zoom = auto_zoom_here(survey_yaml)
    assert (base, zoom) == (12, 15), f"one site: base {base}, zoom {zoom}; expected 12 and 15"
    check_extent_and_meta(survey_yaml, stdout, zoom)
    side = longer_side_px(expected_extent(survey_yaml), zoom)
    print(f"  one site, auto: zoom {zoom} = base {base} + 3, longer side {side:.0f} px")
    relief = "Esri.WorldShadedRelief"
    code, stdout, stderr = run(script, survey_yaml, "--provider", relief)
    assert code == 0, (code, stdout, stderr)
    base, zoom = auto_zoom_here(survey_yaml, relief)
    assert zoom == 13, f"{relief}: zoom {zoom}, expected its max_zoom 13"
    check_extent_and_meta(survey_yaml, stdout, zoom, relief)
    print(f"  one site, --provider {relief}: zoom {zoom}, the provider's max_zoom")


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
        tests = [test_rows_follow_mercator, test_curnamona_extent, test_zoom_rule, test_offline_says_so]
        for test in tests:
            test(script)
            print(f"  ok  {test.__name__}")
    finally:
        contextily.bounds2img = real
    print(f"\nPASS  basemap_unit ({len(tests)} tests, {len(CALLS)} mocked fetches, no network)")
