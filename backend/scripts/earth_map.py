#!/usr/bin/env python3
"""
World-map plate for the mosaic: real coastlines, relief, rivers and lakes drawn
in the engraved-survey style of the ``atlas`` pattern.

Where ``atlas`` invents its geography out of noise, this draws the actual Earth.
The point is recognition. On a canvas with no accounts, a real world map is the
one thing every visitor already shares a vocabulary for: people can agree to
meet "in Japan" without being told where that is, and will claim their own city
without being asked to. A beautiful invented continent gives them none of that.

Data (fetch with ``scripts/fetch_earth_data.py``; all public domain):
    ne_50m_land.geojson                     Natural Earth coastlines, 1:50m
    ne_50m_lakes.geojson                    Natural Earth lakes
    ne_50m_rivers_lake_centerlines.geojson  Natural Earth river centrelines
    gebco_08_rev_elev_21600x10800.png       NASA/GEBCO land elevation, 1 arcmin

The resolutions match almost by luck: 32000 px across 360 deg of longitude is
~1.25 km/px, and both the 1:50m vectors (~1 km) and the 1-arcmin DEM (~1.85 km)
resolve to about that. Real data lands right at this canvas's native detail, so
nothing has to be faked at the scale a viewer actually inspects.

Rendered in full-width horizontal strips rather than tile by tile. The per-tile
pure-function contract that suits noise is wrong for raster-and-vector sources:
every worker process would need its own copy of the rasters (the DEM alone is
233 Mpx), and vectors sampled through a 32 px window lose exactly the crispness
that makes them worth using. Strips keep one copy of the data in one process,
draw the vectors at the full 32000 px width, and carry far less numpy overhead
per pixel than a million tiny arrays do.
"""

import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Shared drawing primitives live with the atlas pattern rather than being copied
# here. init_mosaic must therefore import *this* module lazily, inside the earth
# branch, or the two would form an import cycle.
from init_mosaic import _grad_mag, _over, _smoothstep, _stroke, _value_noise

logger = logging.getLogger(__name__)

# 21600x10800 is 233 Mpx, past PIL's decompression-bomb guard. The file is one
# we fetched ourselves from NASA, so the guard is just in the way here.
Image.MAX_IMAGE_PIXELS = None

DATA_DIR = Path(__file__).parent.parent / "data"

LAND_FILE = "ne_50m_land.geojson"
LAKES_FILE = "ne_50m_lakes.geojson"
RIVERS_FILE = "ne_50m_rivers_lake_centerlines.geojson"
DEM_FILE = "gebco_08_rev_elev_21600x10800.png"

# Must match backend/app/config.py and frontend/src/config.ts.
GRID_WIDTH = 1000
GRID_HEIGHT = 1000
TILE_SIZE = 32

MAP_PX = GRID_WIDTH * TILE_SIZE  # 32000 px, a full 360 deg of longitude
CANVAS_PX = GRID_HEIGHT * TILE_SIZE  # 32000 px

# Equirectangular puts the world in a wide band inside a square canvas, so the
# spare rows above and below carry the plate's furniture.
#
# Cut at 82 deg rather than at the poles, the way a printed wall map does. Two
# reasons beyond taste: equirectangular stretch grows without bound toward the
# poles, and Antarctica's ring reaches exactly -90, where the whole polygon
# degenerates onto a single line and strokes as a solid bar clean across the
# plate. Cropping removes the degeneracy instead of special-casing it.
LAT_LIMIT = 82.0
BAND_H = int(round(MAP_PX * (2.0 * LAT_LIMIT) / 360.0))
BAND_TOP = (CANVAS_PX - BAND_H) // 2
BAND_BOT = BAND_TOP + BAND_H

DEM_MAX = 228.0  # brightest grey present in the GEBCO ramp; 0 is sea
DEM_SMOOTH = 4.5  # output px of low-pass, to kill 8-bit contour terracing
CONTOUR_BANDS = 15
# Real land is overwhelmingly low, so evenly spaced contours would give the
# Himalayas twenty lines and the Russian plain none. Bending the height scale
# with a power law expands the lowlands, which is what hypsometric intervals
# (0, 200, 500, 1000, 2000 m ...) do on a real sheet.
CONTOUR_GAMMA = 0.55

GRATICULE_DEG = 15.0

# Supersample factor for the vector layers. PIL fills and strokes are aliased,
# and the coastline is the single most recognisable line on the plate, so it is
# worth drawing at 2x and box-filtering down to get real coverage values.
SS = 2

# Palette, shared in spirit with the atlas pattern. Paper stays pure white so a
# bare tile is indistinguishable from an absent one and can be skipped.
INK_COAST = (44, 35, 28)
INK_INDEX = (74, 58, 42)
INK_CONTOUR = (132, 110, 84)
INK_RELIEF = (112, 92, 72)
INK_OCEAN = (186, 172, 152)
INK_WATER = (58, 94, 126)
INK_GRAT = (212, 202, 186)
WASH_LAND = (242, 235, 220)
WASH_LAKE = (222, 232, 238)

_FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Didot.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Baskerville.ttc", 0),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", 0),
    ("/System/Library/Fonts/Supplemental/Georgia.ttf", 0),
    ("/Library/Fonts/Times New Roman.ttf", 0),
]

_cache: dict = {}


# =============================================================================
# Data loading
# =============================================================================


def data_available() -> tuple[bool, str]:
    """Report whether every required data file is present."""
    missing = [
        f
        for f in (LAND_FILE, LAKES_FILE, RIVERS_FILE, DEM_FILE)
        if not (DATA_DIR / f).exists()
    ]
    if missing:
        return False, (
            "Missing Earth data in "
            + str(DATA_DIR)
            + ": "
            + ", ".join(missing)
            + "\nFetch it with: python scripts/fetch_earth_data.py"
        )
    return True, ""


def _lon_to_x(lon: np.ndarray) -> np.ndarray:
    return (lon + 180.0) / 360.0 * MAP_PX


def _lat_to_y(lat: np.ndarray) -> np.ndarray:
    return BAND_TOP + (LAT_LIMIT - lat) / (2.0 * LAT_LIMIT) * BAND_H


def _y_to_dem_row(y: float, dem_height: int) -> float:
    """Canvas row to DEM row. The DEM spans the full -90..90, the band does not."""
    lat = LAT_LIMIT - (y - BAND_TOP) / BAND_H * (2.0 * LAT_LIMIT)
    return (90.0 - lat) / 180.0 * dem_height


def _polygon_rings(geom: dict):
    """Yield (exterior, holes) in canvas pixels for polygonal geometry."""
    kind = geom["type"]
    coords = geom["coordinates"]
    if kind == "Polygon":
        yield coords[0], coords[1:]
    elif kind == "MultiPolygon":
        for poly in coords:
            yield poly[0], poly[1:]


def _line_parts(geom: dict):
    """Yield coordinate sequences for linear geometry."""
    kind = geom["type"]
    coords = geom["coordinates"]
    if kind == "LineString":
        yield coords
    elif kind == "MultiLineString":
        yield from coords


def _project(seq) -> np.ndarray:
    """Project a lon/lat sequence to canvas pixels as an Nx2 float32 array."""
    arr = np.asarray(seq, dtype=np.float64)[:, :2]
    out = np.empty_like(arr, dtype=np.float32)
    out[:, 0] = _lon_to_x(arr[:, 0])
    out[:, 1] = _lat_to_y(arr[:, 1])
    return out


def _load() -> dict:
    """
    Load and project every feature once.

    Each entry carries its y-bounds so a strip can cull the ~98% of features it
    does not touch; without that, re-projecting 100k vertices for each of a
    hundred strips dominates the run.
    """
    if _cache:
        return _cache

    ok, why = data_available()
    if not ok:
        raise FileNotFoundError(why)

    land = []
    for feat in json.load(open(DATA_DIR / LAND_FILE))["features"]:
        for ext, holes in _polygon_rings(feat["geometry"]):
            pe = _project(ext)
            land.append(
                (pe, [_project(h) for h in holes], pe[:, 1].min(), pe[:, 1].max())
            )

    lakes = []
    for feat in json.load(open(DATA_DIR / LAKES_FILE))["features"]:
        for ext, holes in _polygon_rings(feat["geometry"]):
            pe = _project(ext)
            lakes.append(
                (pe, [_project(h) for h in holes], pe[:, 1].min(), pe[:, 1].max())
            )

    rivers = []
    for feat in json.load(open(DATA_DIR / RIVERS_FILE))["features"]:
        rank = feat["properties"].get("scalerank") or 6
        # Natural Earth ranks 1 (Nile, Missouri, Mackenzie) to 6 (minor).
        width = {1: 7.0, 2: 6.0, 3: 4.0, 4: 3.0, 5: 2.0}.get(int(rank), 1.5)
        for part in _line_parts(feat["geometry"]):
            if len(part) < 2:
                continue
            pp = _project(part)
            rivers.append((pp, width, pp[:, 1].min(), pp[:, 1].max()))

    dem = Image.open(DATA_DIR / DEM_FILE)
    if dem.mode != "L":
        dem = dem.convert("L")

    _cache.update(land=land, lakes=lakes, rivers=rivers, dem=dem)
    logger.info(
        "Earth data loaded: %d land rings, %d lakes, %d river parts, DEM %s",
        len(land),
        len(lakes),
        len(rivers),
        dem.size,
    )
    return _cache


def _font(size: int):
    """Load a serif face for the plate's lettering, or None if none is found."""
    for path, index in _FONT_CANDIDATES:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index)
            except OSError:
                continue
    return None


# =============================================================================
# Vector rasterising
# =============================================================================


def _flat(arr: np.ndarray, y0: float, scale: float) -> list:
    """Flatten projected coords into the sequence PIL wants, strip-relative."""
    out = arr.astype(np.float64).copy()
    out[:, 1] -= y0
    out *= scale
    return out.ravel().tolist()


def _coverage(
    draw_ops, width: int, height: int, scale: float, y0: float, ss: int = SS
) -> np.ndarray:
    """
    Rasterise vector ops into an antialiased 0..1 coverage array.

    Drawn at ``ss`` times the target size and box-filtered down, because PIL has
    no antialiasing of its own and a hard-edged coastline is the one thing that
    would give this plate away as a bitmap.

    Pass ``ss=1`` for area fills whose edge is later covered by a stroke: the
    land and lake washes sit under a 5 px shoreline, so supersampling them buys
    nothing and each layer at 2x costs another 4 Gpx over the whole plate.
    """
    img = Image.new("L", (width * ss, height * ss), 0)
    draw = ImageDraw.Draw(img)
    draw_ops(draw, scale * ss, y0)
    if ss != 1:
        img = img.resize((width, height), Image.Resampling.BOX)
    return np.asarray(img, dtype=np.float32) / 255.0


def _land_ops(features, y0, y1):
    def ops(draw, scale, oy):
        for ext, holes, ymin, ymax in features["land"]:
            if ymax < y0 or ymin > y1:
                continue
            draw.polygon(_flat(ext, oy, scale), fill=255)
            for hole in holes:
                draw.polygon(_flat(hole, oy, scale), fill=0)

    return ops


def _coast_ops(features, y0, y1, weight):
    def ops(draw, scale, oy):
        w = max(1, int(round(weight * scale)))
        for ext, holes, ymin, ymax in features["land"]:
            if ymax < y0 or ymin > y1:
                continue
            pts = _flat(ext, oy, scale)
            draw.line(pts + pts[:2], fill=255, width=w, joint="curve")
            for hole in holes:
                hp = _flat(hole, oy, scale)
                draw.line(hp + hp[:2], fill=255, width=w, joint="curve")

    return ops


def _lake_fill_ops(features, y0, y1):
    def ops(draw, scale, oy):
        for ext, holes, ymin, ymax in features["lakes"]:
            if ymax < y0 or ymin > y1:
                continue
            draw.polygon(_flat(ext, oy, scale), fill=255)
            for hole in holes:
                draw.polygon(_flat(hole, oy, scale), fill=0)

    return ops


def _lake_edge_ops(features, y0, y1, weight):
    def ops(draw, scale, oy):
        w = max(1, int(round(weight * scale)))
        for ext, holes, ymin, ymax in features["lakes"]:
            if ymax < y0 or ymin > y1:
                continue
            pts = _flat(ext, oy, scale)
            draw.line(pts + pts[:2], fill=255, width=w, joint="curve")

    return ops


def _river_ops(features, y0, y1, gain):
    def ops(draw, scale, oy):
        for pts, width, ymin, ymax in features["rivers"]:
            if ymax < y0 or ymin > y1:
                continue
            w = max(1, int(round(width * gain * scale)))
            draw.line(_flat(pts, oy, scale), fill=255, width=w, joint="curve")

    return ops


# =============================================================================
# Relief
# =============================================================================


def _dem_strip(
    dem: Image.Image, y0: float, y1: float, width: int, height: int
) -> np.ndarray:
    """
    Sample land elevation for canvas rows [y0, y1) onto a `height` x `width` grid.

    ``box`` resamples a fractional sub-rectangle of the source directly, which
    avoids the half-pixel drift of cropping to whole rows and then rescaling.
    Rows outside the map band stay zero: the GEBCO ramp puts sea at zero, so
    "no land here" and "off the map" are the same value by construction.
    """
    out = np.zeros((height, width), dtype=np.float32)
    top = max(y0, float(BAND_TOP))
    bot = min(y1, float(BAND_BOT))
    if bot <= top:
        return out

    span = y1 - y0
    r0 = _y_to_dem_row(top, dem.height)
    r1 = _y_to_dem_row(bot, dem.height)
    y_off = int(round((top - y0) / span * height))
    rows = max(1, min(height - y_off, int(round((bot - top) / span * height))))
    patch = dem.resize(
        (width, rows), Image.Resampling.BICUBIC, box=(0.0, r0, dem.width, r1)
    )
    out[y_off : y_off + rows] = np.asarray(patch, dtype=np.float32)
    return out


# =============================================================================
# Plate furniture
# =============================================================================

# y ranges the lettered furniture occupies, so the ~90% of strips that contain
# none of it skip rasterising a mask for it entirely.
TITLE_SPAN = (1900, 6200)
FOOT_SPAN = (25400, 30600)

_font_cache: dict = {}


def _font_at(size: int):
    size = max(6, int(size))
    if size not in _font_cache:
        _font_cache[size] = _font(size)
    return _font_cache[size]


def _text(draw, xy, label, size, scale, spacing=0.0, anchor="mm"):
    """Draw letter-spaced text, silently skipping if no serif face was found."""
    font = _font_at(size * scale)
    if font is None:
        return
    if not spacing:
        draw.text(xy, label, fill=255, font=font, anchor=anchor)
        return
    # PIL has no tracking control, so wide-spaced small caps are drawn glyph by
    # glyph. Engraved plates letter-space their titles; without it the lettering
    # reads as a word processor rather than a burin.
    gap = spacing * size * scale
    widths = [draw.textlength(ch, font=font) for ch in label]
    total = sum(widths) + gap * (len(label) - 1)
    # Honour the horizontal half of the anchor. Centring unconditionally is what
    # dragged the legend labels back over their own sample strokes.
    x = xy[0] - total / 2.0 if anchor[0] == "m" else xy[0]
    for ch, w in zip(label, widths):
        draw.text((x, xy[1]), ch, fill=255, font=font, anchor="l" + anchor[1])
        x += w + gap


def _compass_ops(draw, scale, oy, cx, cy, radius):
    """An eight-point rose: long cardinal rays, short intercardinal ones."""

    def pt(angle_deg, r):
        a = np.deg2rad(angle_deg)
        return (
            (cx + r * np.sin(a)) * scale,
            (cy - r * np.cos(a) - oy) * scale,
        )

    for i in range(8):
        ang = i * 45.0
        long_ray = i % 2 == 0
        tip = radius if long_ray else radius * 0.52
        half = radius * (0.13 if long_ray else 0.085)
        draw.polygon(
            [pt(ang, tip), pt(ang + 90, half), pt(ang + 180, 0), pt(ang - 90, half)],
            fill=255 if long_ray else 150,
        )
    w = max(1, int(round(3 * scale)))
    for rr in (radius * 1.10, radius * 1.16):
        draw.ellipse(
            [
                (cx - rr) * scale,
                (cy - rr - oy) * scale,
                (cx + rr) * scale,
                (cy + rr - oy) * scale,
            ],
            outline=255,
            width=w,
        )
    _text(draw, pt(0, radius * 1.42), "N", 420, scale)


def _scalebar_ops(draw, scale, oy, cx, cy):
    """
    A bar in kilometres, true at the equator.

    Equirectangular scale is only correct on the equator -- it stretches without
    limit toward the poles -- so the bar says so rather than implying the whole
    plate shares one scale.
    """
    km_per_px = 40075.0 / MAP_PX
    seg_km = 1000.0
    seg = seg_km / km_per_px
    n = 5
    x0 = cx - n * seg / 2.0
    h = 150.0
    for i in range(n):
        box = [
            (x0 + i * seg) * scale,
            (cy - oy) * scale,
            (x0 + (i + 1) * seg) * scale,
            (cy + h - oy) * scale,
        ]
        draw.rectangle(
            box,
            fill=255 if i % 2 == 0 else 0,
            outline=255,
            width=max(1, int(round(3 * scale))),
        )
    for i in range(n + 1):
        _text(
            draw,
            ((x0 + i * seg) * scale, (cy - 190 - oy) * scale),
            f"{int(i * seg_km)}",
            240,
            scale,
        )
    _text(
        draw,
        (cx * scale, (cy + 430 - oy) * scale),
        "KILOMETRES AT THE EQUATOR",
        230,
        scale,
        spacing=0.22,
    )


def _legend_ops(draw, scale, oy, x, y):
    """Key to the four inks used on the plate."""
    w = max(1, int(round(3 * scale)))
    rows = [
        ("COASTLINE", "line", 6.0),
        ("RIVER", "line", 5.0),
        ("CONTOUR", "line", 2.0),
        ("LAKE", "box", 0.0),
    ]
    step = 560.0
    for i, (label, kind, weight) in enumerate(rows):
        yy = y + i * step
        if kind == "line":
            draw.line(
                [
                    (x * scale, (yy - oy) * scale),
                    ((x + 900) * scale, (yy - oy) * scale),
                ],
                fill=255,
                width=max(1, int(round(weight * scale))),
            )
        else:
            draw.rectangle(
                [
                    (x * scale, (yy - 150 - oy) * scale),
                    ((x + 900) * scale, (yy + 150 - oy) * scale),
                ],
                outline=255,
                width=w,
            )
        _text(
            draw,
            ((x + 1120) * scale, (yy - oy) * scale),
            label,
            250,
            scale,
            spacing=0.2,
            anchor="lm",
        )


def _furniture_ops(y0, y1):
    """Lettering, rose, scale bar and legend, culled to the strips that need them."""

    def ops(draw, scale, oy):
        if y1 >= TITLE_SPAN[0] and y0 <= TITLE_SPAN[1]:
            cx = MAP_PX / 2.0
            _text(
                draw,
                (cx * scale, (2450 - oy) * scale),
                "LIVE TESSERAE",
                470,
                scale,
                spacing=0.42,
            )
            _text(
                draw,
                (cx * scale, (4150 - oy) * scale),
                "THE WORLD",
                1500,
                scale,
                spacing=0.14,
            )
            for yy, half in ((3150.0, 5.0), (5250.0, 5.0)):
                draw.line(
                    [
                        (6000 * scale, (yy - oy) * scale),
                        ((MAP_PX - 6000) * scale, (yy - oy) * scale),
                    ],
                    fill=255,
                    width=max(1, int(round(half * scale))),
                )
            _text(
                draw,
                (cx * scale, (5850 - oy) * scale),
                "DRAWN BY MANY HANDS",
                300,
                scale,
                spacing=0.3,
            )

        if y1 >= FOOT_SPAN[0] and y0 <= FOOT_SPAN[1]:
            _compass_ops(draw, scale, oy, 5600.0, 27900.0, 1750.0)
            _scalebar_ops(draw, scale, oy, 16000.0, 27700.0)
            _legend_ops(draw, scale, oy, 23200.0, 26400.0)

    return ops


# =============================================================================
# Strip composition
# =============================================================================

# Canvas rows of context rendered either side of a strip. The coastal shading is
# derived from a blurred land mask, so without this the blur would see a cropped
# world and leave a visible seam at every strip boundary.
STRIP_PAD = 192

COAST_BLUR = 34.0  # output px; ~43 km of coastal shading at full scale


def render_strip(y0: int, y1: int, scale: float = 1.0, seed: int = 1) -> np.ndarray:
    """
    Render canvas rows [y0, y1) of the plate. Returns uint8 RGB.

    ``scale`` below 1 renders a proportionally smaller plate for previewing;
    stroke weights scale with it and floor at one pixel.
    """
    feats = _load()

    ey0 = y0 - STRIP_PAD
    ey1 = y1 + STRIP_PAD
    w = int(round(MAP_PX * scale))
    eh = int(round((ey1 - ey0) * scale))
    row0 = int(round(STRIP_PAD * scale))
    rows = int(round((y1 - y0) * scale))

    xs = (np.arange(w, dtype=np.float32) + 0.5) / scale
    ys = ey0 + (np.arange(eh, dtype=np.float32) + 0.5) / scale

    rgb = np.full((eh, w, 3), 255.0, dtype=np.float32)

    # Everything geographic is confined to the band. Features cut by the 82 deg
    # crop (Antarctica, northern Greenland) project past its edge, and without
    # this they would spill over the rules into the lettering below.
    in_band = (ys >= BAND_TOP) & (ys <= BAND_BOT)
    band = in_band[:, None].astype(np.float32)

    # --- land and relief ---------------------------------------------------
    land_cov = _coverage(_land_ops(feats, ey0, ey1), w, eh, scale, ey0, ss=1) * band
    land = land_cov > 0.5

    dem = _dem_strip(feats["dem"], ey0, ey1, w, eh)
    # The GEBCO ramp is 8-bit, so elevation arrives in ~39 m steps. Contouring
    # that directly makes every quantisation step its own closed loop, which
    # covers gentle terrain (the Hungarian plain especially) in a labyrinth of
    # little cells. Dithering with noise only textured the maze; low-passing
    # removes it, and costs no real signal because the DEM's true resolution is
    # ~1.85 km, or about 1.5 px at this scale.
    if DEM_SMOOTH > 0:
        dem = np.asarray(
            Image.fromarray(np.clip(dem, 0, 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(DEM_SMOOTH * max(scale, 0.06))
            ),
            dtype=np.float32,
        )
    elev = np.clip(dem / DEM_MAX, 0.0, 1.0)

    # --- graticule, under the ink -----------------------------------------
    mer = MAP_PX / (360.0 / GRATICULE_DEG)
    par = BAND_H / (180.0 / GRATICULE_DEG)
    dm = np.minimum(np.mod(xs, mer), mer - np.mod(xs, mer)) * scale
    dp = (
        np.minimum(np.mod(ys - BAND_TOP, par), par - np.mod(ys - BAND_TOP, par)) * scale
    )
    dash_v = (np.mod(ys, 96.0) < 54.0) & in_band
    dash_h = np.mod(xs, 96.0) < 54.0
    grat = np.maximum(
        np.clip(0.5 * scale + 0.5 - dm, 0.0, 1.0)[None, :] * dash_v[:, None],
        np.clip(0.5 * scale + 0.5 - dp, 0.0, 1.0)[:, None]
        * (dash_h[None, :] & in_band[:, None]),
    )
    _over(rgb, grat * 0.9, INK_GRAT)

    _over(rgb, land_cov, WASH_LAND)

    # --- coastal shading: lines parallel to the shore, fading to open water -
    # There is no bathymetry in a land-only DEM, so distance from the coast is
    # approximated by blurring the land mask: the falloff of that blur is a
    # usable stand-in for depth, and its level sets run parallel to the shore.
    blur = (
        np.asarray(
            Image.fromarray((land_cov * 255).astype(np.uint8)).filter(
                ImageFilter.GaussianBlur(COAST_BLUR * max(scale, 0.05))
            ),
            dtype=np.float32,
        )
        / 255.0
    )
    bgrad = _grad_mag(blur)
    for level, weight in ((0.40, 0.75), (0.26, 0.55), (0.15, 0.38), (0.07, 0.24)):
        _over(
            rgb,
            _stroke(blur - level, bgrad, 0.6 * max(scale, 0.35))
            * (~land)
            * band
            * weight,
            INK_OCEAN,
        )

    # --- contours ----------------------------------------------------------
    band_t = np.power(elev, CONTOUR_GAMMA) * CONTOUR_BANDS
    tgrad = np.maximum(_grad_mag(band_t), 1e-9)
    resid = band_t - np.round(band_t)
    on_land = land & (band_t > 0.45)
    is_index = np.mod(np.round(band_t), 5.0) == 0
    _over(
        rgb,
        _stroke(resid, tgrad, 0.55 * max(scale, 0.4)) * (on_land & ~is_index),
        INK_CONTOUR,
    )
    _over(
        rgb,
        _stroke(resid, tgrad, 0.95 * max(scale, 0.4)) * (on_land & is_index),
        INK_INDEX,
    )

    # --- summit stipple ----------------------------------------------------
    stip = _value_noise(xs[None, :] / 2.6, ys[:, None] / 2.6, seed + 4421)
    peak = _smoothstep(0.58, 0.95, elev)
    _over(rgb, (stip > (1.0 - 0.22 * peak)) * land * peak * 0.5, INK_RELIEF)

    # --- lakes -------------------------------------------------------------
    lake_cov = (
        _coverage(_lake_fill_ops(feats, ey0, ey1), w, eh, scale, ey0, ss=1) * band
    )
    _over(rgb, lake_cov, WASH_LAKE)
    hatch = (np.mod(ys, 5.0) < 1.0)[:, None] & (lake_cov > 0.5)
    _over(rgb, hatch * 0.5, INK_WATER)

    # --- rivers and lake shores share one ink, so one mask does both -------
    def water_lines(draw, s, oy):
        _river_ops(feats, ey0, ey1, 1.0)(draw, s, oy)
        _lake_edge_ops(feats, ey0, ey1, 4.0)(draw, s, oy)

    _over(rgb, _coverage(water_lines, w, eh, scale, ey0) * band, INK_WATER)

    # --- coastline last, so it stays crisp over everything it bounds -------
    _over(
        rgb,
        _coverage(_coast_ops(feats, ey0, ey1, 5.0), w, eh, scale, ey0) * band,
        INK_COAST,
    )

    # --- frame and band rules, axis-aligned so numpy is enough -------------
    lo, hi = 200.0, CANVAS_PX - 200.0
    dx = np.minimum(xs - lo, hi - xs)
    dy = np.minimum(ys - lo, hi - ys)
    d = np.minimum(dx[None, :], dy[:, None]) * scale
    frame = np.clip(6.0 * scale + 0.5 - np.abs(d), 0.0, 1.0) + np.clip(
        2.0 * scale + 0.5 - np.abs(d - 70.0 * scale), 0.0, 1.0
    )
    rule = np.minimum(np.abs(ys - BAND_TOP), np.abs(ys - BAND_BOT)) * scale
    frame = np.maximum(
        np.clip(frame, 0.0, 1.0),
        np.clip(2.0 * scale + 0.5 - rule, 0.0, 1.0)[:, None]
        * ((xs > lo) & (xs < hi))[None, :],
    )
    _over(rgb, frame, INK_COAST)

    # --- lettering ---------------------------------------------------------
    if (ey1 >= TITLE_SPAN[0] and ey0 <= TITLE_SPAN[1]) or (
        ey1 >= FOOT_SPAN[0] and ey0 <= FOOT_SPAN[1]
    ):
        _over(rgb, _coverage(_furniture_ops(ey0, ey1), w, eh, scale, ey0), INK_COAST)

    return np.clip(np.rint(rgb[row0 : row0 + rows]), 0, 255).astype(np.uint8)


def render_plate(scale: float = 1.0 / 16.0, rows_per_strip: int = 64) -> Image.Image:
    """Render the whole plate at reduced scale, for previewing composition."""
    strips = []
    step = rows_per_strip * TILE_SIZE
    for y in range(0, CANVAS_PX, step):
        strips.append(render_strip(y, min(y + step, CANVAS_PX), scale=scale))
    return Image.fromarray(np.concatenate(strips, axis=0), "RGB")
