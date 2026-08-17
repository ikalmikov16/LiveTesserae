#!/usr/bin/env python3
"""
Layered-relief world map for the mosaic, in the style of a laser-cut plate.

Oak-toned land with engraved country borders over stepped ocean depth layers,
each layer carrying a light cut highlight and a soft drop shadow so the whole
thing reads as stacked plywood rather than a flat contour map. No lettering.

Why the ocean layers matter structurally: they carry the entire background, so
the continents can sit in their true geographic positions and still fill a
square canvas. Earlier attempts packed the continents like a collage to fill the
frame, which wrecked the country shapes for no gain.

Data (fetch with ``scripts/fetch_earth_data.py``; all public domain):
    ne_50m_admin_0_countries_lakes.geojson   land + CONTINENT tags, lakes as holes
    ne_50m_admin_0_boundary_lines_land.geojson  country borders
    gebco_08_rev_bath_21600x10800.png        NASA/GEBCO bathymetry (255 = sea level)

Rendered region by region rather than whole-canvas: 32000x32000 in float RGB is
12 GB. Fields that are smooth by construction (depth bands, coast distance, the
land's shadow rim) are precomputed once for the whole world at GLOBAL_RES and
upsampled per region; only the vector layers, whose crispness is the point, are
rasterised at full resolution.
"""

import json
import logging
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

logger = logging.getLogger(__name__)

# The bathymetry is 233 Mpx, past PIL's decompression-bomb guard. We fetched it
# ourselves from NASA, so the guard is only in the way.
Image.MAX_IMAGE_PIXELS = None

DATA_DIR = Path(__file__).parent.parent / "data"
COUNTRIES_FILE = "ne_50m_admin_0_countries_lakes.geojson"
BORDERS_FILE = "ne_50m_admin_0_boundary_lines_land.geojson"
BATHY_FILE = "gebco_08_rev_bath_21600x10800.png"

# Must match backend/app/config.py and frontend/src/config.ts.
GRID_WIDTH = 1000
GRID_HEIGHT = 1000
TILE_SIZE = 32
CANVAS = GRID_WIDTH * TILE_SIZE  # 32000

# Resolution at which the smooth fields are precomputed for the whole world.
# They are all blurs or heavily generalised rasters, so representing them here
# and interpolating up costs nothing visible while making the memory tractable.
GLOBAL_RES = 4096

# Everything below was tuned against a reference plate at 2000 px; widths scale
# from that so the look is resolution-independent.
REF = 2000.0

LAT_TOP, LAT_BOT = 89.0, -89.0
BANDS = 9
# The bathymetry is area-averaged onto this grid before banding -- an absolute
# resolution, deliberately. Expressing it as a fraction of the output size makes
# the amount of generalisation depend on the render size, and the plate then
# looks nothing like its own preview: at 32000 px it kept every mid-ocean ridge
# and fracture zone, where the 2000 px mockup had smoothed them into broad
# sheets. ~125 cells across the world is about 300 km per cell.
GENERALISE_RES = 125
DEPTH_GAMMA = 0.62
# Fraction of the banding taken from distance-to-coast rather than depth. The
# reference's shallow layers hug every coastline at near-uniform width, which is
# an offset curve, not a bathymetric contour; raw depth alone bands the
# mid-ocean ridges and reads as noise.
COAST_MIX = 0.55

# A square frame holding 360 deg of longitude and 178 of latitude forces a 2.02x
# vertical stretch, which leaves every continent too tall and narrow. Spend the
# vertical budget unevenly instead: latitudes below 48 deg keep close to true
# proportions (1.31x) and the squeeze lands above 65 deg, which is almost all
# ocean and ice. Cropping longitude would be the alternative and costs New
# Zealand, Hawaii and most of Alaska.
POLAR_BIAS = 1.95
RAMP_LO, RAMP_HI = 48.0, 80.0

# Per-landmass size corrections, applied after projection.
#
# Widening the tropics is what inflates the poles -- the same latitude scale that
# puts Africa at 1.31x puts Greenland and Antarctica near 3.9x -- so no single
# global dial fixes both. These four are corrected directly. Greenland and
# Antarctica are ringed by water, so shrinking them tears nothing; the depth
# layers simply close in around them.
#
# The anchor is load-bearing. Scaling Africa about its centre fused it with
# Arabia and closed the Red Sea; "northeast" pins its north and east edges so all
# the growth goes west and south into open ocean. Antarctica scales toward the
# bottom of the frame so it stays welded to the edge instead of drifting up.
# Verified with the overlap check in ``audit_collisions``.
REGION_ADJUST = {
    "greenland": ((0.72, 0.66), "centroid", (0.0, 0.0)),
    "antarctica": ((0.94, 0.44), "bottom", (0.0, 0.0)),
    "africa": ((1.20, 1.20), "northeast", (0.0, 0.0)),
    "south_america": ((1.27, 1.27), "northeast", (-0.022, 0.004)),
}

# Sampled off the reference plate: pale shelf through to deep navy.
RAMP_ANCHORS = [
    (0.00, (223, 239, 247)),
    (0.12, (176, 224, 240)),
    (0.28, (118, 202, 230)),
    (0.44, (62, 172, 212)),
    (0.60, (30, 136, 190)),
    (0.74, (20, 100, 163)),
    (0.86, (14, 70, 133)),
    (1.00, (7, 34, 84)),
]

LAND = (223, 200, 162)  # light oak
INK_COAST = (74, 52, 32)
INK_BORDER = (140, 108, 74)
LAYER_HILIGHT = (255, 255, 255)
LAYER_SHADOW = (0, 0, 0)

SS = 2  # supersample for vector layers; PIL has no antialiasing of its own

# Vector stroke weights in absolute canvas pixels, NOT scaled from the reference.
# The reference was only ever viewed as a whole world at 2000 px, where a 2.6 px
# coastline looks elegant; scaling that up by 16 for a 32000 px canvas gives a
# 42 px rope, which at zoom 1 and 2 -- the levels people actually draw at --
# swamps the map. Fills survive downsampling and strokes do not, so the oak land
# and the depth bands are what carry zoom 0; the strokes are sized for zoom 1-2
# and simply average into a soft edge at zoom 0.
COAST_PX = 8.0
BORDER_PX = 4.5

# Context rendered around each region. Sized for the layer shadow: a 64 px offset
# plus a 48 px blur. The smooth fields need none, being global already.
PAD = 224

_cache: dict = {}


def data_available() -> tuple[bool, str]:
    """Report whether every required data file is present."""
    missing = [
        f
        for f in (COUNTRIES_FILE, BORDERS_FILE, BATHY_FILE)
        if not (DATA_DIR / f).exists()
    ]
    if missing:
        return False, (
            "Missing world-map data in "
            + str(DATA_DIR)
            + ": "
            + ", ".join(missing)
            + "\nFetch it with: python scripts/fetch_earth_data.py"
        )
    return True, ""


# =============================================================================
# Projection
# =============================================================================

_lat_tab = np.linspace(LAT_TOP, LAT_BOT, 20001)
_ramp = np.clip((np.abs(_lat_tab) - RAMP_LO) / max(RAMP_HI - RAMP_LO, 1e-6), 0.0, 1.0)
_density = 1.0 + POLAR_BIAS * (_ramp * _ramp * (3.0 - 2.0 * _ramp))
_dlat = abs(_lat_tab[1] - _lat_tab[0])
_cum = np.concatenate([[0.0], np.cumsum((_density[:-1] + _density[1:]) * 0.5 * _dlat)])
_y_tab = _cum / _cum[-1] * CANVAS
_lat_asc = _lat_tab[::-1]
_y_desc = _y_tab[::-1]


def stretch_at(lat: float) -> float:
    """Vertical exaggeration versus a true equirectangular map, at a latitude."""
    d = float(np.interp(lat, _lat_asc, _density[::-1]))
    return 360.0 * d / float(_cum[-1])


def lon_to_x(lon):
    return (np.asarray(lon, dtype=np.float64) + 180.0) / 360.0 * CANVAS


def lat_to_y(lat):
    return np.interp(np.asarray(lat, dtype=np.float64), _lat_asc, _y_desc)


def y_to_lat(y):
    return np.interp(np.asarray(y, dtype=np.float64), _y_tab, _lat_tab)


def _rings(geom, polys=True):
    kind, coords = geom["type"], geom["coordinates"]
    if polys:
        if kind == "Polygon":
            yield coords[0], coords[1:]
        elif kind == "MultiPolygon":
            for poly in coords:
                yield poly[0], poly[1:]
    else:
        if kind == "LineString":
            yield coords
        elif kind == "MultiLineString":
            yield from coords


def _project(seq) -> np.ndarray:
    a = np.asarray(seq, dtype=np.float64)[:, :2]
    return np.stack([lon_to_x(a[:, 0]), lat_to_y(a[:, 1])], axis=1)


def _region_of(props) -> str | None:
    if (props.get("NAME") or "") == "Greenland":
        return "greenland"
    return {
        "Antarctica": "antarctica",
        "Africa": "africa",
        "South America": "south_america",
    }.get(props.get("CONTINENT"))


def _ramp_colors(n: int) -> np.ndarray:
    xs = np.array([a for a, _ in RAMP_ANCHORS])
    cs = np.array([c for _, c in RAMP_ANCHORS], dtype=np.float64)
    ts = np.linspace(0, 1, n)
    return np.stack([np.interp(ts, xs, cs[:, i]) for i in range(3)], axis=1)


# =============================================================================
# Load and adjust
# =============================================================================


def _bbox(pts: np.ndarray) -> tuple[float, float, float, float]:
    return (pts[:, 0].min(), pts[:, 1].min(), pts[:, 0].max(), pts[:, 1].max())


def load() -> dict:
    """Load, project and size-correct every feature once."""
    if _cache:
        return _cache

    ok, why = data_available()
    if not ok:
        raise FileNotFoundError(why)

    countries = json.load(open(DATA_DIR / COUNTRIES_FILE))
    borders = json.load(open(DATA_DIR / BORDERS_FILE))

    raw = []
    for feat in countries["features"]:
        reg = _region_of(feat["properties"] or {})
        for ext, holes in _rings(feat["geometry"]):
            raw.append((_project(ext), [_project(h) for h in holes], reg))

    xform = {}
    for reg, (scale, anchor, nudge) in REGION_ADJUST.items():
        pts = np.concatenate([e for e, _, r in raw if r == reg], axis=0)
        if anchor == "centroid":
            ax, ay = pts[:, 0].mean(), pts[:, 1].mean()
        elif anchor == "north":
            ax, ay = pts[:, 0].mean(), pts[:, 1].min()
        elif anchor == "northeast":
            ax, ay = pts[:, 0].max(), pts[:, 1].min()
        else:  # bottom of frame
            ax, ay = pts[:, 0].mean(), float(CANVAS)
        xform[reg] = (scale[0], scale[1], ax, ay, nudge[0] * CANVAS, nudge[1] * CANVAS)

    def adjust(p, reg):
        if reg not in xform:
            return p
        sx, sy, ax, ay, nx, ny = xform[reg]
        out = np.asarray(p, dtype=np.float64).copy()
        out[:, 0] = (out[:, 0] - ax) * sx + ax + nx
        out[:, 1] = (out[:, 1] - ay) * sy + ay + ny
        return out

    land = []
    for ext, holes, reg in raw:
        pe = adjust(ext, reg)
        land.append((pe, [adjust(h, reg) for h in holes], _bbox(pe), reg))

    # A border is assigned to the landmass whose area its centroid falls in, via
    # a raster of the *unadjusted* regions, so it moves with the land it divides.
    rid_w, rid_h = 1200, 1200
    names = list(REGION_ADJUST.keys())
    rid = Image.new("L", (rid_w, rid_h), 0)
    draw = ImageDraw.Draw(rid)
    for i, reg in enumerate(names, start=1):
        for ext, _, r in raw:
            if r == reg:
                draw.polygon(
                    [(x / CANVAS * rid_w, y / CANVAS * rid_h) for x, y in ext], fill=i
                )
    rid_arr = np.asarray(rid)

    border_lines = []
    for feat in borders["features"]:
        for part in _rings(feat["geometry"], polys=False):
            if len(part) < 2:
                continue
            pp = _project(part)
            cx = int(np.clip(pp[:, 0].mean() / CANVAS * rid_w, 0, rid_w - 1))
            cy = int(np.clip(pp[:, 1].mean() / CANVAS * rid_h, 0, rid_h - 1))
            v = int(rid_arr[cy, cx])
            pa = adjust(pp, names[v - 1] if v else None)
            border_lines.append((pa, _bbox(pa)))

    _cache.update(land=land, borders=border_lines)
    logger.info("world data: %d land rings, %d borders", len(land), len(border_lines))
    return _cache


def audit_collisions(res: int = 1400) -> list[str]:
    """
    Report land overlaps created by the size corrections.

    Africa genuinely touches Asia at Sinai and South America touches Panama, so
    the correct overlap is never zero -- the baseline with all scales at 1.0 is
    what a result has to be compared against. Scaling Africa about its centre
    instead of its north-east corner raised its overlap far past baseline: that
    was the Red Sea closing.
    """
    feats = load()
    out = []

    def mask(pred):
        img = Image.new("L", (res, res), 0)
        d = ImageDraw.Draw(img)
        k = res / CANVAS
        for ext, holes, _bb, reg in feats["land"]:
            if not pred(reg):
                continue
            d.polygon((ext * k).ravel().tolist(), fill=255)
            for h in holes:
                d.polygon((h * k).ravel().tolist(), fill=0)
        return np.asarray(img) > 127

    af = mask(lambda r: r == "africa")
    sa = mask(lambda r: r == "south_america")
    rest = mask(lambda r: r not in ("africa", "south_america"))
    for name, a, b in (
        ("africa/rest", af, rest),
        ("south-america/rest", sa, rest),
        ("africa/south-america", af, sa),
    ):
        out.append(f"{name}={int((a & b).sum())}px")
    return out


# =============================================================================
# Global smooth fields
# =============================================================================


def _blur(arr: np.ndarray, radius: float) -> np.ndarray:
    """Gaussian blur a 0..1 float field via PIL."""
    if radius <= 0:
        return arr
    img = Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), np.float32) / 255.0


def _global_fields() -> dict:
    """
    Precompute, for the whole world at GLOBAL_RES: the depth-band field `t`, and
    the blurred land rim used for the pale shore layer and the land's shadow.

    These have to be global. The coast-distance term reaches thousands of pixels
    offshore, so a per-region computation would see a cropped world and leave a
    seam at every region boundary. They are all blurs or heavily generalised
    rasters, so computing them here and interpolating up loses nothing.
    """
    if "t" in _cache:
        return _cache

    feats = load()
    G = GLOBAL_RES
    k = G / CANVAS

    img = Image.new("L", (G, G), 0)
    d = ImageDraw.Draw(img)
    for ext, holes, _bb, _r in feats["land"]:
        d.polygon((ext * k).ravel().tolist(), fill=255)
        for h in holes:
            d.polygon((h * k).ravel().tolist(), fill=0)
    land_lo = np.asarray(img, np.float32) / 255.0
    is_land = land_lo > 0.5

    # Distance-from-coast proxy: summed blurs at increasing radii. A single
    # Gaussian wide enough to reach the middle of the Pacific would be enormous,
    # and stacking scales gives a smoother ramp anyway.
    fine = _blur(land_lo, 7.0 * G / REF)
    small = Image.fromarray((land_lo * 255).astype(np.uint8)).resize(
        (256, 256), Image.Resampling.BOX
    )
    acc = np.zeros((256, 256), np.float32)
    for r in (2.0, 6.0, 16.0, 44.0):
        acc += np.asarray(small.filter(ImageFilter.GaussianBlur(r)), np.float32)
    acc /= 4.0 * 255.0
    far = (
        np.asarray(
            Image.fromarray((acc * 255).astype(np.uint8)).resize(
                (G, G), Image.Resampling.BICUBIC
            ),
            np.float32,
        )
        / 255.0
    )
    near = 0.45 * fine + 0.55 * far
    sea = near[~is_land]
    lo, hi = np.percentile(sea, [2.0, 98.0]) if sea.size else (0.0, 1.0)
    coast = np.clip(1.0 - (near - lo) / max(hi - lo, 1e-6), 0.0, 1.0)

    # Bathymetry, generalised then resampled through the non-uniform latitude
    # scale. A PIL box crop cannot express the second step: its crop is linear in
    # the source and our rows are not.
    bath_img = Image.open(DATA_DIR / BATHY_FILE).convert("L")
    r0 = (90.0 - LAT_TOP) / 180.0 * bath_img.height
    r1 = (90.0 - LAT_BOT) / 180.0 * bath_img.height
    coarse = GENERALISE_RES
    gen = np.asarray(
        bath_img.resize(
            (coarse, coarse), Image.Resampling.BOX, box=(0.0, r0, bath_img.width, r1)
        ),
        np.float32,
    )
    bath_img.close()

    src = (
        (LAT_TOP - y_to_lat((np.arange(G) + 0.5) / k))
        / (LAT_TOP - LAT_BOT)
        * (coarse - 1)
    )
    lo_i = np.clip(np.floor(src).astype(np.int64), 0, coarse - 1)
    hi_i = np.clip(lo_i + 1, 0, coarse - 1)
    frac = (src - lo_i).astype(np.float32)[:, None]
    rows = gen[lo_i] * (1.0 - frac) + gen[hi_i] * frac
    bath = np.asarray(
        Image.fromarray(np.clip(rows, 0, 255).astype(np.uint8)).resize(
            (G, G), Image.Resampling.BICUBIC
        ),
        np.float32,
    )
    # Scales with the coarse cell size, or the band thresholds latch onto the
    # downsample grid and the deep ocean comes out in rectangular stair-steps.
    bath = _blur(bath / 255.0, 0.7 * G / coarse) * 255.0

    depth = np.clip((255.0 - bath) / 255.0, 0.0, 1.0)
    t = ((1.0 - COAST_MIX) * np.power(depth, DEPTH_GAMMA) + COAST_MIX * coast) * BANDS

    rim = _blur(land_lo, 5.0 * G / REF)

    _cache.update(t=t.astype(np.float32), rim=rim.astype(np.float32))
    logger.info("global fields ready at %dx%d", G, G)
    return _cache


def _upsample(field: np.ndarray, x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """
    Crop a GLOBAL_RES field to a canvas rect and interpolate to full size.

    The rect is the region plus its padding ring, so at the canvas border it
    extends outside the world -- and PIL rejects a negative crop box. Clamp to
    the canvas, upsample that, then replicate the edge outward to refill the
    padding.
    """
    G = field.shape[0]
    k = G / CANVAS
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(CANVAS, x0 + w), min(CANVAS, y0 + h)
    # Resized as float, not 8-bit. The band field feeds a contour-distance
    # calculation, and quantising it to 1/255 leaves plateaus that turn the layer
    # edges into scratchy noise instead of clean steps.
    img = Image.fromarray(np.ascontiguousarray(field, dtype=np.float32), mode="F")
    arr = np.asarray(
        img.resize(
            (cx1 - cx0, cy1 - cy0),
            Image.Resampling.BICUBIC,
            box=(cx0 * k, cy0 * k, cx1 * k, cy1 * k),
        ),
        np.float32,
    )
    pads = ((cy0 - y0, (y0 + h) - cy1), (cx0 - x0, (x0 + w) - cx1))
    if any(p for pair in pads for p in pair):
        arr = np.pad(arr, pads, mode="edge")
    return arr


# =============================================================================
# Region rendering
# =============================================================================


def _coverage(ops, w: int, h: int, ox: float, oy: float, ss: int = SS) -> np.ndarray:
    """Rasterise vector ops into an antialiased 0..1 coverage array."""
    img = Image.new("L", (w * ss, h * ss), 0)
    ops(ImageDraw.Draw(img), ss, ox, oy)
    if ss != 1:
        img = img.resize((w, h), Image.Resampling.BOX)
    return np.asarray(img, np.float32) / 255.0


def _hits(bb, x0, y0, x1, y1) -> bool:
    return not (bb[2] < x0 or bb[0] > x1 or bb[3] < y0 or bb[1] > y1)


def _flat(pts: np.ndarray, ss: float, ox: float, oy: float) -> list:
    out = pts.copy()
    out[:, 0] = (out[:, 0] - ox) * ss
    out[:, 1] = (out[:, 1] - oy) * ss
    return out.ravel().tolist()


def _over(rgb: np.ndarray, alpha: np.ndarray, ink) -> None:
    a = alpha[..., None] if alpha.ndim == 2 else alpha
    rgb *= 1.0 - a
    rgb += a * np.asarray(ink, np.float32)


def render_region(x0: int, y0: int, w: int, h: int) -> np.ndarray:
    """Render the canvas rect at (x0, y0) of size w x h. Returns uint8 RGB."""
    feats = _global_fields()
    scale = CANVAS / REF  # width multiplier vs the 2000 px reference

    ex0, ey0 = x0 - PAD, y0 - PAD
    ew, eh = w + 2 * PAD, h + 2 * PAD
    ex1, ey1 = ex0 + ew, ey0 + eh

    t = _upsample(feats["t"] / BANDS, ex0, ey0, ew, eh) * BANDS
    rim = _upsample(feats["rim"], ex0, ey0, ew, eh)

    pal = _ramp_colors(BANDS)
    band = np.clip(np.floor(t).astype(np.int32), 0, BANDS - 1)
    rgb = pal[band].astype(np.float32)

    # --- layer edges: light cut highlight plus a shadow on the deeper side ----
    gy, gx = np.gradient(t)
    dist = np.abs(t - np.round(t)) / np.maximum(np.hypot(gx, gy), 1e-9)
    edge = np.clip(1.5 * scale + 0.5 - dist, 0.0, 1.0)
    off = max(1, int(round(4.0 * scale)))
    shadow = np.roll(np.roll(_blur(edge, 3.0 * scale), off, axis=0), off, axis=1)
    _over(rgb, shadow * 0.34, LAYER_SHADOW)
    _over(rgb, edge * 0.34, LAYER_HILIGHT)

    # --- land -----------------------------------------------------------------
    def land_ops(d, ss, ox, oy):
        for ext, holes, bb, _r in feats["land"]:
            if not _hits(bb, ex0, ey0, ex1, ey1):
                continue
            d.polygon(_flat(ext, ss, ox, oy), fill=255)
            for hole in holes:
                d.polygon(_flat(hole, ss, ox, oy), fill=0)

    land_cov = _coverage(land_ops, ew, eh, ex0, ey0, ss=1)
    is_land = land_cov > 0.5

    # Pale rim just offshore, like the topmost cut layer hugging the land.
    _over(rgb, np.clip((rim - 0.06) * 1.9, 0, 1) * (~is_land) * 0.85, pal[0])
    # Land is the topmost sheet, so it throws its own shadow on the water.
    lshadow = np.roll(np.roll(rim, off, axis=0), off, axis=1)
    _over(rgb, np.clip(lshadow * 1.4, 0, 1) * (~is_land) * 0.30, LAYER_SHADOW)
    _over(rgb, land_cov, LAND)

    def border_ops(d, ss, ox, oy):
        width = max(1, int(round(BORDER_PX * ss)))
        for pts, bb in feats["borders"]:
            if not _hits(bb, ex0, ey0, ex1, ey1):
                continue
            d.line(_flat(pts, ss, ox, oy), fill=255, width=width)

    _over(rgb, _coverage(border_ops, ew, eh, ex0, ey0) * 0.85, INK_BORDER)

    def coast_ops(d, ss, ox, oy):
        width = max(1, int(round(COAST_PX * ss)))
        for ext, holes, bb, _r in feats["land"]:
            if not _hits(bb, ex0, ey0, ex1, ey1):
                continue
            pts = _flat(ext, ss, ox, oy)
            d.line(pts + pts[:2], fill=255, width=width, joint="curve")
            for hole in holes:
                hp = _flat(hole, ss, ox, oy)
                d.line(hp + hp[:2], fill=255, width=width, joint="curve")

    _over(rgb, _coverage(coast_ops, ew, eh, ex0, ey0), INK_COAST)

    out = rgb[PAD : PAD + h, PAD : PAD + w]
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def iter_tile_rows(region_tiles: int = 100):
    """
    Yield (tile_y, tiles_array) for the whole plate, region by region.

    ``tiles_array`` is (GRID_WIDTH, 32, 32, 3) uint8 for one row of tiles.
    Regions are square and chunk-sized by default: padding is a fixed ring, so a
    square region wastes far less of it than a full-width strip would.
    """
    span = region_tiles * TILE_SIZE
    for ty0 in range(0, GRID_HEIGHT, region_tiles):
        rows = min(region_tiles, GRID_HEIGHT - ty0)
        band = np.empty((rows * TILE_SIZE, GRID_WIDTH * TILE_SIZE, 3), np.uint8)
        for tx0 in range(0, GRID_WIDTH, region_tiles):
            cols = min(region_tiles, GRID_WIDTH - tx0)
            part = render_region(
                tx0 * TILE_SIZE, ty0 * TILE_SIZE, cols * TILE_SIZE, rows * TILE_SIZE
            )
            band[:, tx0 * TILE_SIZE : (tx0 + cols) * TILE_SIZE] = part
        for r in range(rows):
            row = band[r * TILE_SIZE : (r + 1) * TILE_SIZE]
            tiles = np.ascontiguousarray(
                row.reshape(TILE_SIZE, GRID_WIDTH, TILE_SIZE, 3).transpose(1, 0, 2, 3)
            )
            yield ty0 + r, tiles
        del band


def render_preview(size: int = 2000, region_tiles: int = 100) -> Image.Image:
    """
    Whole plate at reduced size, for eyeballing before a full run.

    Assembled from the same square regions the real fill uses. Rendering
    full-width bands instead would need 1.4 GB of float RGB per band.
    """
    out = Image.new("RGB", (size, size), (255, 255, 255))
    span = region_tiles * TILE_SIZE
    for ty0 in range(0, GRID_HEIGHT, region_tiles):
        rows = min(region_tiles, GRID_HEIGHT - ty0)
        for tx0 in range(0, GRID_WIDTH, region_tiles):
            cols = min(region_tiles, GRID_WIDTH - tx0)
            part = Image.fromarray(
                render_region(
                    tx0 * TILE_SIZE, ty0 * TILE_SIZE, cols * TILE_SIZE, rows * TILE_SIZE
                )
            )
            dx0 = round(tx0 * TILE_SIZE / CANVAS * size)
            dy0 = round(ty0 * TILE_SIZE / CANVAS * size)
            dx1 = round((tx0 + cols) * TILE_SIZE / CANVAS * size)
            dy1 = round((ty0 + rows) * TILE_SIZE / CANVAS * size)
            out.paste(
                part.resize((dx1 - dx0, dy1 - dy0), Image.Resampling.LANCZOS),
                (dx0, dy0),
            )
    return out
