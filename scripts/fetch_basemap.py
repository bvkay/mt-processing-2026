"""Fetch a map background for the GUI's site map, once, while online.

Usage:
    python scripts/fetch_basemap.py <survey.yaml> [--provider NAME] [--margin FRACTION]
        [--zoom N|auto]

The extent is every site in `survey.yaml` with a latitude and a longitude,
padded on each side by --margin of its span (default 0.15), and by at least
0.1 degree. The tiles come from an xyzservices provider through contextily:
OpenTopoMap by default, or any dotted xyzservices name (Esri.WorldTopoMap,
Esri.WorldImagery, OpenStreetMap.Mapnik, ...). They arrive in Web Mercator;
this script warps them, with numpy alone, onto the plain latitude-longitude
grid the site map draws on -- every output row takes the source row at the
Mercator y of its latitude, every output column the source column at the
Mercator x of its longitude, linearly interpolated -- and writes

    <workspace>/basemap.png    RGB, north up, its pixel edges on the extent
    <workspace>/basemap.json   lon_min, lon_max, lat_min, lat_max, provider,
                               attribution, zoom, fetched (UTC ISO), width, height

The GUI never goes online: the Process tab's site map draws that image under
the sites when both files exist, and its "Fetch basemap" button queues this
script. It needs internet, and says so (exit 1) when the tiles cannot be had.
--zoom auto is contextily's own rule, the coarser of ceil(log2(720 / span))
over the longitude and latitude spans, kept inside the provider's zoom range.
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

from bbmt.survey import Survey  # noqa: E402

EARTH_RADIUS_M = 6378137.0  # the Web Mercator (EPSG:3857) sphere
MIN_PAD_DEG = 0.1
PNG_NAME, JSON_NAME = "basemap.png", "basemap.json"
USER_AGENT = "bbmt-2026 scripts/fetch_basemap.py (MT survey site map; contextily)"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fetch_basemap.py", description=__doc__.split("\n\nUsage:")[0])
    p.add_argument("survey_yaml")
    p.add_argument("--provider", default="OpenTopoMap",
                   help="xyzservices name, e.g. OpenTopoMap, Esri.WorldTopoMap, Esri.WorldImagery")
    p.add_argument("--margin", type=float, default=0.15,
                   help="padding on each side as a fraction of the sites' span (at least 0.1 deg)")
    p.add_argument("--zoom", default="auto", help="tile zoom level N, or auto")
    return p


def site_extent(survey: Survey) -> tuple[float, float, float, float]:
    """(west, south, east, north) of every site that declares a latitude and a longitude."""
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
    """Each axis padded on both sides by max(margin * span, 0.1 deg)."""
    w, s, e, n = extent
    pad_x = max(margin * (e - w), MIN_PAD_DEG)
    pad_y = max(margin * (n - s), MIN_PAD_DEG)
    return w - pad_x, s - pad_y, e + pad_x, n + pad_y


def provider_named(name: str) -> TileProvider:
    """An xyzservices TileProvider from a dotted name ("Esri.WorldImagery")."""
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


def auto_zoom(w: float, s: float, e: float, n: float, provider: TileProvider) -> int:
    """contextily's automatic zoom for the extent, inside the provider's zoom range."""
    zoom = int(min(math.ceil(math.log2(720.0 / (e - w))), math.ceil(math.log2(720.0 / (n - s)))))
    return max(int(provider.get("min_zoom", 0)), min(zoom, int(provider.get("max_zoom", 19))))


def mercator_x(lon):
    return EARTH_RADIUS_M * np.radians(lon)


def mercator_y(lat):
    return EARTH_RADIUS_M * np.log(np.tan(np.pi / 4.0 + np.radians(lat) / 2.0))


def _lerp(a: np.ndarray, index: np.ndarray, axis: int) -> np.ndarray:
    """`a` sampled at fractional positions `index` along `axis`, linearly, clamped to its ends."""
    index = np.clip(index, 0.0, a.shape[axis] - 1.0)
    below = np.floor(index).astype(int)
    above = np.minimum(below + 1, a.shape[axis] - 1)
    shape = [1] * a.ndim
    shape[axis] = -1
    frac = (index - below).reshape(shape)
    return np.take(a, below, axis=axis) * (1.0 - frac) + np.take(a, above, axis=axis) * frac


def warp_to_latlon(img: np.ndarray, merc_extent, extent) -> np.ndarray:
    """A Web Mercator mosaic resampled onto a regular lon/lat grid over `extent`, north row first.

    `merc_extent` is contextily's (left, right, bottom, top) in metres, the
    mosaic's pixel edges; `extent` is (west, south, east, north) in degrees,
    which become the output's pixel edges. The output keeps about the
    mosaic's own pixel size: as many columns as source columns span the
    longitudes, as many rows as source rows span the Mercator y of the
    latitudes.
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
    args = build_parser().parse_args(argv)
    survey = Survey.from_yaml(Path(args.survey_yaml).resolve())
    w, s, e, n = extent = padded_extent(site_extent(survey), args.margin)
    provider = provider_named(args.provider)
    zoom = auto_zoom(w, s, e, n, provider) if str(args.zoom) == "auto" else int(args.zoom)
    try:
        img, merc_extent = cx.bounds2img(w, s, e, n, ll=True, source=provider, zoom=zoom,
                                         headers={"user-agent": USER_AGENT}, timeout=30)
    except Exception as exc:  # no network, a refused tile, a bad zoom: all the same to the user
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
