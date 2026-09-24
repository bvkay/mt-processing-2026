# -*- coding: utf-8 -*-
"""
Fetch a map background for the GUI's site map

Fetches the basemap once, while online. The extent is every site in
`survey.yaml` with a latitude and a longitude, padded on each side by
--margin of its span (default 0.15) and by at least 0.1 degree. The tiles
come from an xyzservices provider through contextily. The default is
Esri.WorldImagery, satellite imagery without place names (Esri serves its
labels as a separate reference layer, which is not fetched), so the site
names are the only text on the map. Any dotted xyzservices name works:
Esri.WorldShadedRelief (relief, no labels, zoom 13 at most),
CartoDB.PositronNoLabels (plain grey), OpenTopoMap (contours and town names),
OpenStreetMap.Mapnik, and so on.

The tiles arrive in Web Mercator. The script warps them with numpy onto the
plain latitude-longitude grid the site map draws on: every output row takes
the source row at the Mercator y of its latitude and every output column the
source column at the Mercator x of its longitude, linearly interpolated. It
writes

    <workspace>/basemap.png    RGB, north up, its pixel edges on the extent
    <workspace>/basemap.json   lon_min, lon_max, lat_min, lat_max, provider,
                               attribution, zoom, fetched (UTC ISO), width, height

The site map of the Process tab draws the image under the sites when both
files exist. Opening a survey whose workspace has no basemap.json runs this
script once (`site_map.fetch_basemap_if_missing`); this script is the GUI's
only network access. It needs internet and exits 1 with a message when the
tiles cannot be fetched; every tile request times out after 30 s.

--zoom auto (the default) starts three levels finer than contextily's own
rule (the coarser of ceil(log2(720 / span)) over the longitude and latitude
spans), for a sharper map. It then coarsens one level at a time, down to
contextily's level at most, until it is inside the provider's zoom range (19
when xyzservices gives none) and the image's longer side is at most 8000 px
(`pick_zoom`).

Usage:
    python scripts/fetch_basemap.py <survey.yaml> [--provider NAME] [--margin FRACTION]
        [--zoom N|auto]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import contextily as cx  # noqa: E402
import numpy as np  # noqa: E402
import xyzservices.providers as xyz  # noqa: E402
from PIL import Image  # noqa: E402
from xyzservices import TileProvider  # noqa: E402

from mtproc.survey import Survey  # noqa: E402

EARTH_RADIUS_M = 6378137.0  # the Web Mercator (EPSG:3857) sphere
TILE_PX = 256  # a slippy-map tile's side: at zoom z the world is TILE_PX * 2**z pixels round
MIN_PAD_DEG = 0.1
DEFAULT_PROVIDER = "Esri.WorldImagery"  # imagery, no place names
FINER_ZOOM = 3  # --zoom auto: this many levels finer than contextily's rule ...
MAX_SIDE_PX = 8000  # ... unless the image's longer side would pass this
DEFAULT_MAX_ZOOM = 19  # a provider xyzservices gives no max_zoom for (Esri.WorldImagery)
PNG_NAME, JSON_NAME = "basemap.png", "basemap.json"
USER_AGENT = "mt-processing-2026 scripts/fetch_basemap.py (MT survey site map; contextily)"


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of fetch_basemap.py."""
    p = argparse.ArgumentParser(prog="fetch_basemap.py",
                                description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("survey_yaml")
    p.add_argument("--provider", default=DEFAULT_PROVIDER,
                   help="xyzservices name, e.g. Esri.WorldImagery (default: no labels), "
                        "Esri.WorldShadedRelief, CartoDB.PositronNoLabels, OpenTopoMap")
    p.add_argument("--margin", type=float, default=0.15,
                   help="padding on each side as a fraction of the sites' span (at least 0.1 deg)")
    p.add_argument("--zoom", default="auto",
                   help=f"tile zoom level N, or auto (contextily's + {FINER_ZOOM}, longer side <= {MAX_SIDE_PX} px)")
    return p


def site_extent(survey: Survey) -> tuple[float, float, float, float]:
    """Return the extent of the sites that declare a latitude and a longitude.

    Args:
        survey (Survey): The survey.

    Returns:
        tuple[float, float, float, float]: (west, south, east, north) in
        degrees.

    Raises:
        SystemExit: When no site declares a position.
    """
    lons, lats = [], []
    for name in survey.site_names():
        cfg = survey.site(name)
        if cfg.latitude is not None and cfg.longitude is not None:
            lons.append(float(cfg.longitude))
            lats.append(float(cfg.latitude))
    if not lons:
        raise SystemExit("no site in the survey declares a latitude and a longitude")
    return min(lons), min(lats), max(lons), max(lats)


def padded_extent(extent, margin: float) -> tuple[float, float, float, float]:
    """Pad an extent on both sides of each axis by max(margin * span, 0.1 deg).

    Args:
        extent (tuple): (west, south, east, north) in degrees.
        margin (float): Padding as a fraction of the span.

    Returns:
        tuple[float, float, float, float]: The padded extent.
    """
    w, s, e, n = extent
    pad_x = max(margin * (e - w), MIN_PAD_DEG)
    pad_y = max(margin * (n - s), MIN_PAD_DEG)
    return w - pad_x, s - pad_y, e + pad_x, n + pad_y


def provider_named(name: str) -> TileProvider:
    """Look up an xyzservices TileProvider by name.

    Args:
        name (str): Dotted name ("Esri.WorldImagery"), or a name that
            `xyz.query_name` resolves.

    Returns:
        TileProvider: The provider.

    Raises:
        SystemExit: When the name is unknown or names a family of providers.
    """
    node = xyz
    try:
        for part in name.split("."):
            node = node[part]
    except KeyError:
        try:
            node = xyz.query_name(name)
        except ValueError:
            raise SystemExit(f"unknown provider {name!r}: use an xyzservices name, e.g. OpenTopoMap")
    if not isinstance(node, TileProvider):
        raise SystemExit(f"{name!r} is a family of providers, pick one: {', '.join(node)}")
    return node


def zoom_range(provider: TileProvider) -> tuple[int, int]:
    """Return the provider's (min_zoom, max_zoom), with DEFAULT_MAX_ZOOM when unset."""
    return int(provider.get("min_zoom", 0)), int(provider.get("max_zoom", DEFAULT_MAX_ZOOM))


def auto_zoom(w: float, s: float, e: float, n: float, provider: TileProvider) -> int:
    """Return contextily's automatic zoom for the extent, clamped to the provider's range."""
    zoom = int(min(math.ceil(math.log2(720.0 / (e - w))), math.ceil(math.log2(720.0 / (n - s)))))
    low, high = zoom_range(provider)
    return max(low, min(zoom, high))


def image_size(w: float, s: float, e: float, n: float, zoom: int) -> tuple[int, int]:
    """Return the (width, height) in px of the warped image at `zoom`.

    Each side is the extent's size in Mercator metres divided by the size of
    a tile pixel at that zoom.
    """
    pixel_m = 2.0 * math.pi * EARTH_RADIUS_M / (TILE_PX * 2 ** zoom)
    return (int(round(float(mercator_x(e) - mercator_x(w)) / pixel_m)),
            int(round(float(mercator_y(n) - mercator_y(s)) / pixel_m)))


def pick_zoom(w: float, s: float, e: float, n: float, provider: TileProvider) -> int:
    """Choose the zoom for --zoom auto.

    Starts at contextily's level + FINER_ZOOM, within the provider's range,
    and coarsens one level at a time, down to contextily's level at most,
    while the image's longer side exceeds MAX_SIDE_PX.

    Returns:
        int: The zoom level.
    """
    base = auto_zoom(w, s, e, n, provider)
    zoom = min(base + FINER_ZOOM, zoom_range(provider)[1])
    while zoom > base and max(image_size(w, s, e, n, zoom)) > MAX_SIDE_PX:
        zoom -= 1
    return zoom


def mercator_x(lon):
    """Web Mercator x in metres of a longitude in degrees."""
    return EARTH_RADIUS_M * np.radians(lon)


def mercator_y(lat):
    """Web Mercator y in metres of a latitude in degrees."""
    return EARTH_RADIUS_M * np.log(np.tan(np.pi / 4.0 + np.radians(lat) / 2.0))


def _lerp(a: np.ndarray, index: np.ndarray, axis: int) -> np.ndarray:
    """Sample `a` linearly at fractional positions along one axis.

    Args:
        a (np.ndarray): Array to sample.
        index (np.ndarray): Fractional positions, clamped to the array's ends.
        axis (int): Axis to sample along.

    Returns:
        np.ndarray: The interpolated array.
    """
    index = np.clip(index, 0.0, a.shape[axis] - 1.0)
    below = np.floor(index).astype(int)
    above = np.minimum(below + 1, a.shape[axis] - 1)
    shape = [1] * a.ndim
    shape[axis] = -1
    frac = (index - below).reshape(shape)
    return np.take(a, below, axis=axis) * (1.0 - frac) + np.take(a, above, axis=axis) * frac


def warp_to_latlon(img: np.ndarray, merc_extent, extent) -> np.ndarray:
    """Resample a Web Mercator mosaic onto a regular lon/lat grid.

    The output keeps about the mosaic's own pixel size: as many columns as
    source columns span the longitudes, as many rows as source rows span the
    Mercator y of the latitudes.

    Args:
        img (np.ndarray): Tile mosaic from contextily.
        merc_extent (tuple): contextily's (left, right, bottom, top) in
            metres, the mosaic's pixel edges.
        extent (tuple): (west, south, east, north) in degrees, which become
            the output's pixel edges.

    Returns:
        np.ndarray: uint8 RGB image over `extent`, north row first.
    """
    left, right, bottom, top = merc_extent
    rows_in, cols_in = img.shape[:2]
    dx, dy = (right - left) / cols_in, (top - bottom) / rows_in
    w, s, e, n = extent
    width = max(1, int(round((mercator_x(e) - mercator_x(w)) / dx)))
    height = max(1, int(round((mercator_y(n) - mercator_y(s)) / dy)))
    lons = w + (np.arange(width) + 0.5) * (e - w) / width
    lats = n - (np.arange(height) + 0.5) * (n - s) / height
    src_cols = (mercator_x(lons) - left) / dx - 0.5  # pixel centres sit half a pixel in
    src_rows = (top - mercator_y(lats)) / dy - 0.5  # row 0 is the mosaic's top (north)
    rgb = img[..., :3].astype(np.float64)
    out = _lerp(_lerp(rgb, src_rows, axis=0), src_cols, axis=1)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def main(argv=None) -> int:
    """Fetch the tiles, warp them and write basemap.png and basemap.json.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 on success, 1 when the tiles cannot be fetched.
    """
    args = build_parser().parse_args(argv)
    survey = Survey.from_yaml(Path(args.survey_yaml).resolve())
    w, s, e, n = extent = padded_extent(site_extent(survey), args.margin)
    provider = provider_named(args.provider)
    zoom = pick_zoom(w, s, e, n, provider) if str(args.zoom) == "auto" else int(args.zoom)
    width, height = image_size(w, s, e, n, zoom)
    how = (f"auto: contextily's {auto_zoom(w, s, e, n, provider)} + {FINER_ZOOM}, at most {MAX_SIDE_PX} px"
           if str(args.zoom) == "auto" else "asked for")
    print(f"fetching {provider.name} tiles at zoom {zoom} ({how}): about {width}x{height} px ...", flush=True)
    try:
        img, merc_extent = cx.bounds2img(w, s, e, n, ll=True, source=provider, zoom=zoom,
                                         headers={"user-agent": USER_AGENT}, timeout=30)
    except Exception as exc:  # no network, a refused tile or a bad zoom: reported the same way
        print(f"could not fetch {provider.name} tiles at zoom {zoom}: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        print("fetch_basemap.py needs internet; the site map works without a basemap.", file=sys.stderr)
        return 1
    rgb = warp_to_latlon(np.asarray(img), merc_extent, extent)

    workspace = survey.workspace
    workspace.mkdir(parents=True, exist_ok=True)
    png, meta = workspace / PNG_NAME, workspace / JSON_NAME
    Image.fromarray(rgb, "RGB").save(png)
    info = {
        "lon_min": w, "lon_max": e, "lat_min": s, "lat_max": n,
        "provider": provider.name, "attribution": provider.get("attribution", ""),
        "zoom": zoom, "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "width": int(rgb.shape[1]), "height": int(rgb.shape[0]),
    }
    meta.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {png}")
    print(f"wrote {meta}")
    print(f"basemap: {provider.name} zoom {zoom}, {info['width']}x{info['height']} px, "
          f"lon {w:.4f}..{e:.4f}, lat {s:.4f}..{n:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
