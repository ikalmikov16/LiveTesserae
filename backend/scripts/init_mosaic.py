#!/usr/bin/env python3
"""
Initialize the mosaic with pre-generated tiles.

This script can draw various patterns across the entire mosaic canvas.
It writes tiles directly to the database as RGB bytes using batch inserts.

OPTIMIZED VERSION: Uses numpy for fast pattern generation, multiprocessing
for parallel tile generation, and batch database inserts for ~100x faster writes.

Usage:
    python scripts/init_mosaic.py --pattern gradient
    python scripts/init_mosaic.py --pattern mandelbrot
    python scripts/init_mosaic.py --pattern checkerboard
    python scripts/init_mosaic.py --pattern plasma
    python scripts/init_mosaic.py --pattern world --replace  # Layered relief world
    python scripts/init_mosaic.py --pattern earth --replace  # Engraved world map
    python scripts/init_mosaic.py --pattern atlas --replace  # Invented continent
    python scripts/init_mosaic.py --pattern atlas --seed 7   # A different one
    python scripts/init_mosaic.py --pattern image --image-path photo.jpg
    python scripts/init_mosaic.py --pattern white  # Fill with blank white tiles
    python scripts/init_mosaic.py --pattern clear  # Remove all tiles
"""

import argparse
import asyncio
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Add parent directory to path so we can import from app
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from PIL import Image

# Configuration - should match backend settings
GRID_WIDTH = 1000
GRID_HEIGHT = 1000
TILE_SIZE = 32
CHUNK_SIZE = 100

# Number of parallel workers (use most CPUs but leave some for system)
NUM_WORKERS = max(1, (os.cpu_count() or 4) - 2)

# Database batch size (larger = faster, but more memory)
DB_BATCH_SIZE = 5000


def rgb_array_to_bytes(rgb_array: np.ndarray) -> bytes:
    """
    Convert a numpy RGB array (32x32x3) to raw bytes (3072 bytes).
    """
    if rgb_array.shape != (TILE_SIZE, TILE_SIZE, 3):
        raise ValueError(
            f"Expected shape ({TILE_SIZE}, {TILE_SIZE}, 3), got {rgb_array.shape}"
        )
    return rgb_array.astype(np.uint8).tobytes()


# =============================================================================
# Vectorized Pattern Generators (using numpy for speed)
# =============================================================================


def generate_gradient_tile(x: int, y: int) -> bytes:
    """Generate a rainbow gradient tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)

    base_hue = (x / GRID_WIDTH + y / GRID_HEIGHT) / 2
    local_offset = (
        px_grid / TILE_SIZE / GRID_WIDTH + py_grid / TILE_SIZE / GRID_HEIGHT
    ) / 2
    hue = (base_hue + local_offset) % 1.0

    sat, val = 0.8, 0.9
    c = val * sat
    h_prime = hue * 6
    x_val = c * (1 - np.abs(h_prime % 2 - 1))

    r = np.zeros_like(hue)
    g = np.zeros_like(hue)
    b = np.zeros_like(hue)

    for i in range(6):
        mask = (h_prime >= i) & (h_prime < i + 1)
        if i == 0:
            r[mask], g[mask], b[mask] = c, x_val[mask], 0
        elif i == 1:
            r[mask], g[mask], b[mask] = x_val[mask], c, 0
        elif i == 2:
            r[mask], g[mask], b[mask] = 0, c, x_val[mask]
        elif i == 3:
            r[mask], g[mask], b[mask] = 0, x_val[mask], c
        elif i == 4:
            r[mask], g[mask], b[mask] = x_val[mask], 0, c
        elif i == 5:
            r[mask], g[mask], b[mask] = c, 0, x_val[mask]

    m = val - c
    rgb = np.stack(
        [
            ((r + m) * 255).astype(np.uint8),
            ((g + m) * 255).astype(np.uint8),
            ((b + m) * 255).astype(np.uint8),
        ],
        axis=-1,
    )

    return rgb_array_to_bytes(rgb)


def hsv_to_rgb_vectorized(
    h: np.ndarray, s: float, v: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Convert HSV to RGB (vectorized numpy implementation)."""
    c = v * s
    h_prime = h * 6
    x = c * (1 - np.abs(h_prime % 2 - 1))
    m = v - c

    r = np.zeros_like(h)
    g = np.zeros_like(h)
    b = np.zeros_like(h)

    for i in range(6):
        mask = (h_prime >= i) & (h_prime < i + 1)
        if i == 0:
            r[mask], g[mask], b[mask] = c, x[mask], 0
        elif i == 1:
            r[mask], g[mask], b[mask] = x[mask], c, 0
        elif i == 2:
            r[mask], g[mask], b[mask] = 0, c, x[mask]
        elif i == 3:
            r[mask], g[mask], b[mask] = 0, x[mask], c
        elif i == 4:
            r[mask], g[mask], b[mask] = x[mask], 0, c
        elif i == 5:
            r[mask], g[mask], b[mask] = c, 0, x[mask]

    return r + m, g + m, b + m


def generate_mandelbrot_tile(x: int, y: int, max_iter: int = 100) -> bytes:
    """Generate a Mandelbrot fractal tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)

    real_min, real_max = -2.5, 1.0
    imag_min, imag_max = -1.2, 1.2

    mosaic_x = (x * TILE_SIZE + px_grid) / (GRID_WIDTH * TILE_SIZE)
    mosaic_y = (y * TILE_SIZE + py_grid) / (GRID_HEIGHT * TILE_SIZE)

    c_real = real_min + mosaic_x * (real_max - real_min)
    c_imag = imag_min + mosaic_y * (imag_max - imag_min)
    c = c_real + 1j * c_imag

    z = np.zeros_like(c)
    iterations = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.int32)
    mask = np.ones((TILE_SIZE, TILE_SIZE), dtype=bool)

    for i in range(max_iter):
        z[mask] = z[mask] * z[mask] + c[mask]
        escaped = np.abs(z) > 2
        iterations[mask & escaped] = i
        mask = mask & ~escaped

    iterations[mask] = max_iter

    in_set = iterations == max_iter
    hue = (iterations / max_iter) % 1.0

    r, g, b = hsv_to_rgb_vectorized(hue, 0.9, 0.9)
    r[in_set], g[in_set], b[in_set] = 0, 0, 0

    rgb = np.stack(
        [
            (r * 255).astype(np.uint8),
            (g * 255).astype(np.uint8),
            (b * 255).astype(np.uint8),
        ],
        axis=-1,
    )

    return rgb_array_to_bytes(rgb)


def generate_checkerboard_tile(x: int, y: int, square_size: int = 4) -> bytes:
    """Generate a checkerboard pattern tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)

    global_x = x * TILE_SIZE + px_grid
    global_y = y * TILE_SIZE + py_grid
    is_dark = ((global_x // square_size) + (global_y // square_size)) % 2 == 0

    rgb = np.zeros((TILE_SIZE, TILE_SIZE, 3), dtype=np.uint8)
    rgb[is_dark] = [50, 50, 50]
    rgb[~is_dark] = [205, 205, 205]

    return rgb_array_to_bytes(rgb)


def generate_plasma_tile(x: int, y: int, time_val: float = 0) -> bytes:
    """Generate a plasma effect tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)

    gx = (x * TILE_SIZE + px_grid) / 50.0
    gy = (y * TILE_SIZE + py_grid) / 50.0

    v = (
        np.sin(gx + time_val)
        + np.sin(gy + time_val)
        + np.sin((gx + gy) / 2 + time_val)
        + np.sin(np.sqrt(gx * gx + gy * gy) + time_val)
    ) / 4.0
    hue = (v + 1) / 2

    r, g, b = hsv_to_rgb_vectorized(hue, 0.8, 0.9)

    rgb = np.stack(
        [
            (r * 255).astype(np.uint8),
            (g * 255).astype(np.uint8),
            (b * 255).astype(np.uint8),
        ],
        axis=-1,
    )

    return rgb_array_to_bytes(rgb)


def generate_white_tile(x: int, y: int) -> bytes:
    """Generate a solid white tile."""
    rgb = np.full((TILE_SIZE, TILE_SIZE, 3), 255, dtype=np.uint8)
    return rgb_array_to_bytes(rgb)


def generate_noise_tile(x: int, y: int) -> bytes:
    """Generate a random noise tile using numpy (vectorized)."""
    # Use deterministic seed based on coordinates for reproducibility
    np.random.seed((x * 1000 + y) % (2**31))

    base_hue = ((x * 17 + y * 31) % 256) / 256.0
    hue = (base_hue + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.1) % 1.0
    sat = 0.5 + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.3
    val = 0.7 + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.3

    c = val * sat
    h_prime = hue * 6
    x_val = c * (1 - np.abs(h_prime % 2 - 1))
    m = val - c

    r = np.zeros_like(hue)
    g = np.zeros_like(hue)
    b = np.zeros_like(hue)

    for i in range(6):
        mask = (h_prime >= i) & (h_prime < i + 1)
        if i == 0:
            r[mask], g[mask], b[mask] = c[mask], x_val[mask], 0
        elif i == 1:
            r[mask], g[mask], b[mask] = x_val[mask], c[mask], 0
        elif i == 2:
            r[mask], g[mask], b[mask] = 0, c[mask], x_val[mask]
        elif i == 3:
            r[mask], g[mask], b[mask] = 0, x_val[mask], c[mask]
        elif i == 4:
            r[mask], g[mask], b[mask] = x_val[mask], 0, c[mask]
        elif i == 5:
            r[mask], g[mask], b[mask] = c[mask], 0, x_val[mask]

    rgb = np.stack(
        [
            ((r + m) * 255).astype(np.uint8),
            ((g + m) * 255).astype(np.uint8),
            ((b + m) * 255).astype(np.uint8),
        ],
        axis=-1,
    )

    return rgb_array_to_bytes(rgb)


# =============================================================================
# Atlas: an engraved survey map of a procedurally generated continent
# =============================================================================
#
# Drawn for the three zoom levels the viewer actually has, so that zooming
# reveals different information rather than the same shapes magnified:
#   Level 0 (~2 px/tile)   continent silhouette, mountain mass, ruled frame
#   Level 1 (~20 px/tile)  coastline detail, contour bands, river networks
#   Level 2 (32 px/tile)   individual strokes, lake hatching, summit stipple
#
# Every field below is a pure function of *global* mosaic pixel coordinates.
# That is what lets tiles generated in different worker processes agree exactly
# along their shared edges. Seeding a per-tile RNG the way generate_noise_tile
# does would put a hard seam every 32 px: invisible at level 2, glaring at
# level 1.

MAP_PX = GRID_WIDTH * TILE_SIZE  # 32000 px across the whole mosaic

# Feature scale: the coarsest noise octave spans MAP_PX / _MAP_SCALE pixels.
_MAP_SCALE = 3.0
_WARP = 0.085  # domain-warp strength, in fractions of the map width
_HEIGHT_OCTAVES = 12  # finest height detail ~5 px; strokes supply the rest
_CONTRAST = 1.35  # stretch around the fBm mean, or summits never rise
_SEA = 0.44  # sea level in height units
_RELIEF = 0.32  # height range from shore to summit

# 20 bands rather than a dozen. Level 0 downsamples 32000 px to 2048, so a
# 1 px stroke lands on 1/16 of a pixel there and washes out; what gives the
# continent its mass at that zoom is contour *density* averaging to grey, the
# same way it does on a real engraved sheet seen from across a room.
_CONTOUR_STEP = _RELIEF / 24.0
_OCEAN_STEP = 0.030  # spacing of the coastal shading lines
_OCEAN_FADE = 0.075  # depth over which that shading peters out

# One-pixel skirt around each tile so np.gradient sees real neighbours at the
# tile edge instead of a one-sided difference. Line widths are derived from
# those gradients, so without it every tile would get a subtly heavier border.
_PAD = 1

# Paper is pure white on purpose. chunk_renderer composites onto white, so a
# tile of bare paper is indistinguishable from an absent one — which is why
# generate_atlas_tile returns None for it rather than storing 3072 bytes of
# nothing. A cream paper would force us to store every tile and would show a
# visible patchwork wherever one was skipped.
_INK_COAST = (48, 38, 30)  # shoreline, frame
_INK_INDEX = (74, 58, 42)  # every fifth contour
_INK_CONTOUR = (128, 106, 80)  # intermediate contours
_INK_RELIEF = (112, 92, 72)  # summit stipple
_INK_OCEAN = (182, 168, 148)  # coastal shading
_INK_WATER = (62, 98, 128)  # rivers, lakes
_INK_GRAT = (214, 204, 188)  # graticule

# Land gets a flat wash under the line work. This is the one element that
# survives to zoom 0: strokes are downsampled 15.6:1 there, so a 2 px coastline
# lands on an eighth of a pixel and the continent vanishes into the paper
# (measured: a lowland chunk came back at mean luma 253/255, invisible). Only
# filled area carries that far, and a tint is what a real engraved sheet uses
# anyway. Kept pale enough that a land tile still reads as blank canvas at
# zoom 2, and the ocean stays pure white so open water is still skippable.
_WASH_LAND = (242, 235, 220)

_HASH_MASK = np.int64(0xFFFFFFFF)


def _lattice_hash(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic value in [0, 1) at an integer lattice point (vectorized)."""
    h = (ix * np.int64(374761393)) & _HASH_MASK
    h = (h + iy * np.int64(668265263)) & _HASH_MASK
    h = (h + np.int64((seed * 2246822519) & 0xFFFFFFFF)) & _HASH_MASK
    h = ((h ^ (h >> np.int64(13))) * np.int64(1274126177)) & _HASH_MASK
    h = h ^ (h >> np.int64(16))
    return h.astype(np.float64) / 4294967296.0


def _value_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """Smooth value noise on the integer lattice, in [0, 1]."""
    fx = np.floor(x)
    fy = np.floor(y)
    tx = x - fx
    ty = y - fy
    ix = fx.astype(np.int64)
    iy = fy.astype(np.int64)

    # Quintic smoothstep: its second derivative is continuous, so contours
    # derived from this field do not kink as they cross a lattice line.
    sx = tx * tx * tx * (tx * (tx * 6.0 - 15.0) + 10.0)
    sy = ty * ty * ty * (ty * (ty * 6.0 - 15.0) + 10.0)

    n00 = _lattice_hash(ix, iy, seed)
    n10 = _lattice_hash(ix + 1, iy, seed)
    n01 = _lattice_hash(ix, iy + 1, seed)
    n11 = _lattice_hash(ix + 1, iy + 1, seed)

    top = n00 + (n10 - n00) * sx
    bot = n01 + (n11 - n01) * sx
    return top + (bot - top) * sy


def _fbm(
    x: np.ndarray, y: np.ndarray, seed: int, octaves: int, gain: float = 0.5
) -> np.ndarray:
    """Fractal Brownian motion: stacked octaves of value noise, in [0, 1]."""
    total = np.zeros_like(x)
    amplitude = 1.0
    norm = 0.0
    freq = 1.0
    for i in range(octaves):
        total += amplitude * _value_noise(x * freq, y * freq, seed + i * 1013)
        norm += amplitude
        amplitude *= gain
        freq *= 2.0
    return total / norm


def _smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    """Hermite ease between two edges, clamped to [0, 1]."""
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _grad_mag(field: np.ndarray) -> np.ndarray:
    """Magnitude of a scalar field's gradient, per pixel step."""
    dy, dx = np.gradient(field)
    return np.hypot(dx, dy)


def _stroke(field: np.ndarray, grad: np.ndarray, half_width: float) -> np.ndarray:
    """
    Antialiased coverage for a constant-width stroke along ``field == 0``.

    Dividing the field value by its gradient converts it to an approximate
    distance in pixels, which is what keeps a line the same visual weight on a
    cliff (where the field changes fast) and on a plain (where it barely
    changes at all).
    """
    dist = np.abs(field) / np.maximum(grad, 1e-9)
    return np.clip(half_width + 0.5 - dist, 0.0, 1.0)


def _over(rgb: np.ndarray, alpha: np.ndarray, ink: tuple[int, int, int]) -> None:
    """Composite a single ink over the paper in place."""
    a = alpha[..., None]
    rgb *= 1.0 - a
    rgb += a * np.asarray(ink, dtype=np.float64)


def _atlas_terrain(
    u: np.ndarray, v: np.ndarray, seed: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Elevation and warped coordinates for normalized map positions.

    Returns (height, warped_u, warped_v). The warped coordinates are handed
    back so the hydrology can be evaluated in the same distorted space as the
    terrain — rivers that ignore the warp read as though they were painted on
    top of the land rather than cut into it.
    """
    nx = u * _MAP_SCALE
    ny = v * _MAP_SCALE

    # Displacing the *lookup* rather than the output is what turns round noise
    # blobs into capes, fjords and peninsulas.
    wx = _fbm(nx * 0.6 + 11.3, ny * 0.6 - 4.1, seed + 7717, 3)
    wy = _fbm(nx * 0.6 - 2.7, ny * 0.6 + 8.9, seed + 5591, 3)
    wu = u + _WARP * (2.0 * wx - 1.0)
    wv = v + _WARP * (2.0 * wy - 1.0)

    # Stacking octaves averages towards the mean, so raw fBm is a low-contrast
    # field: left alone it puts every summit within a few contour bands of the
    # shore. Stretching around the mean is what buys a real range of elevation.
    h = (
        0.5
        + (_fbm(wu * _MAP_SCALE, wv * _MAP_SCALE, seed, _HEIGHT_OCTAVES) - 0.5)
        * _CONTRAST
    )

    # Drown the edges of the frame so the land reads as one continent at level
    # 0. Measured on the warped position so the falloff is as irregular as the
    # coast it shapes, and subtracted rather than multiplied so relief keeps
    # its contrast near the shore instead of flattening into it.
    d = np.hypot(2.0 * wu - 1.0, 2.0 * wv - 1.0) / 1.4142135623730951
    return h - 0.85 * _smoothstep(0.62, 1.05, d), wu, wv


def _atlas_paint(gx: np.ndarray, gy: np.ndarray, seed: int) -> np.ndarray:
    """
    Draw the map over a padded grid of global pixel coordinates.

    Returns a float RGB array the same shape as the inputs; the caller crops
    the padding away.
    """
    u = gx / MAP_PX
    v = gy / MAP_PX

    h, wu, wv = _atlas_terrain(u, v, seed)
    hgrad = _grad_mag(h)
    land = h > _SEA
    elev = np.clip((h - _SEA) / _RELIEF, 0.0, 1.0)

    rgb = np.full(gx.shape + (3,), 255.0)

    # --- graticule, laid under the ink like a real survey sheet -------------
    # Dashed, every 50 tiles, so most tiles it crosses keep some bare paper.
    dash_x = np.mod(gy, 48.0) < 26.0
    dash_y = np.mod(gx, 48.0) < 26.0
    grat = ((np.mod(gx, 1600.0) < 1.0) & dash_x) | ((np.mod(gy, 1600.0) < 1.0) & dash_y)
    _over(rgb, grat * 0.85, _INK_GRAT)

    # --- land wash, laid under every stroke that follows --------------------
    _over(rgb, land * 1.0, _WASH_LAND)

    # --- ocean: shading lines hugging the coast, fading to open water ------
    depth = _SEA - h
    ot = depth / _OCEAN_STEP
    oresid = (ot - np.round(ot)) * _OCEAN_STEP
    ocean = _stroke(oresid, hgrad, 0.9) * (~land) * np.exp(-depth / _OCEAN_FADE)
    _over(rgb, ocean, _INK_OCEAN)

    # --- land: topographic contours, every fifth one an index contour ------
    ct = (h - _SEA) / _CONTOUR_STEP
    band = np.round(ct)
    cresid = (ct - band) * _CONTOUR_STEP
    on_land = land & (band >= 1)
    is_index = np.mod(band, 5.0) == 0

    _over(rgb, _stroke(cresid, hgrad, 0.85) * (on_land & ~is_index), _INK_CONTOUR)
    _over(rgb, _stroke(cresid, hgrad, 1.45) * (on_land & is_index), _INK_INDEX)

    # --- summits: stipple that thickens with height ------------------------
    # Evaluated in pixel space, not map space: a texture meant to read as
    # individual specks at level 2 needs a wavelength of a few pixels, and
    # anything expressed as a multiple of _MAP_SCALE lands three orders of
    # magnitude coarser than that and fills the summits with solid grey.
    # Sparse on purpose: interpolated value noise is a bell-shaped field, not a
    # scatter of points, so a threshold generous enough to read as "texture"
    # instead connects into a sand dune that buries the contours under it.
    stip = _value_noise(gx / 2.6, gy / 2.6, seed + 4421)
    peak = _smoothstep(0.78, 1.05, elev)
    _over(rgb, (stip > (1.0 - 0.22 * peak)) * land * peak * 0.5, _INK_RELIEF)

    # --- lakes: outlined, hatched the way a survey sheet marks still water --
    # The frequency here has to be high enough that a lake is lake-sized. At a
    # multiple of 1.6 the field varied over ~6600 px, so a "lake" spanned
    # hundreds of tiles and hatched entire coastal plains up to the shoreline.
    lake_n = _fbm(
        wu * _MAP_SCALE * 14.0 + 61.1, wv * _MAP_SCALE * 14.0 + 23.9, seed + 9137, 3
    )
    # Still water collects in low ground. Folding elevation into the field
    # rather than masking on it keeps a lake's edge its own shoreline: a hard
    # `elev < k` cut instead slices lakes off along a contour, leaving straight
    # edges that read as a rendering fault at level 0.
    lake_f = lake_n - (0.74 + 0.30 * _smoothstep(0.20, 0.60, elev))
    lake_grad = _grad_mag(lake_f)
    hatch = np.mod(gy, 5.0) < 1.0
    _over(rgb, land * (lake_f > 0.0) * hatch * 0.75, _INK_WATER)
    _over(rgb, _stroke(lake_f, lake_grad, 0.7) * land, _INK_WATER)

    # --- rivers: the zero-set of an fBm is a connected dendritic network ----
    # Two tiers, so level 0 shows trunk rivers and level 1 reveals the
    # tributaries feeding them. Trunks widen as they approach the sea.
    trunk = (
        2.0
        * _fbm(
            wu * _MAP_SCALE * 3.2 + 31.7, wv * _MAP_SCALE * 3.2 - 17.3, seed + 2203, 6
        )
        - 1.0
    )
    trunk_w = 0.8 + 2.0 * (1.0 - elev)
    _over(
        rgb,
        _stroke(trunk, _grad_mag(trunk), trunk_w) * land * (elev < 0.88),
        _INK_WATER,
    )

    trib = (
        2.0
        * _fbm(
            wu * _MAP_SCALE * 8.5 - 51.9, wv * _MAP_SCALE * 8.5 + 44.2, seed + 6607, 4
        )
        - 1.0
    )
    _over(
        rgb,
        _stroke(trib, _grad_mag(trib), 0.7) * land * (elev > 0.22) * (elev < 0.92),
        _INK_WATER,
    )

    # --- coastline last, so it stays crisp over everything it bounds -------
    _over(rgb, _stroke(h - _SEA, hgrad, 2.0), _INK_COAST)

    # --- ruled frame -------------------------------------------------------
    lo, hi = 300.0, MAP_PX - 300.0
    edge = np.minimum(np.minimum(gx - lo, hi - gx), np.minimum(gy - lo, hi - gy))
    frame = np.clip(2.0 - np.abs(edge), 0.0, 1.0) + np.clip(
        1.0 - np.abs(edge - 22.0), 0.0, 1.0
    )
    _over(rgb, np.clip(frame, 0.0, 1.0), _INK_COAST)

    return rgb


def generate_atlas_tile(x: int, y: int, seed: int = 1) -> bytes | None:
    """
    Generate one tile of the engraved atlas.

    Returns None when the tile is bare paper, so the caller can skip storing
    it: a line map inks well under a third of the mosaic, and the tiles it
    leaves blank are both free and the point — they are what collaborators
    have room to draw on.
    """
    span = TILE_SIZE + 2 * _PAD
    offsets = np.arange(span, dtype=np.float64) - _PAD
    gx, gy = np.meshgrid(x * TILE_SIZE + offsets, y * TILE_SIZE + offsets)

    rgb = _atlas_paint(gx, gy, seed)[_PAD:-_PAD, _PAD:-_PAD]
    out = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)

    if bool((out == 255).all()):
        return None
    return rgb_array_to_bytes(out)


# Pre-scaled source image for image pattern
_source_image_array: np.ndarray | None = None


def init_source_image(image_path: str) -> None:
    """Load and prepare source image for multiprocessing."""
    global _source_image_array
    img = Image.open(image_path).convert("RGB")
    img = img.resize(
        (GRID_WIDTH * TILE_SIZE, GRID_HEIGHT * TILE_SIZE), Image.Resampling.LANCZOS
    )
    _source_image_array = np.array(img)


def generate_image_tile(x: int, y: int) -> bytes:
    """Generate a tile from the pre-loaded source image."""
    global _source_image_array
    if _source_image_array is None:
        raise ValueError("Source image not initialized")

    start_x = x * TILE_SIZE
    start_y = y * TILE_SIZE
    tile_array = _source_image_array[
        start_y : start_y + TILE_SIZE, start_x : start_x + TILE_SIZE
    ]

    return rgb_array_to_bytes(tile_array)


# =============================================================================
# Parallel Processing (CPU-bound tile generation)
# =============================================================================


def process_tile_batch(args: tuple) -> list[tuple[int, int, bytes]]:
    """
    Process a batch of tiles. Returns list of (x, y, pixel_data).

    A generator may return None to mean "this tile is blank, do not store it",
    in which case it is dropped here — so the returned list can be shorter than
    the batch it was given.
    """
    pattern, tiles, image_path, seed = args

    if pattern == "image" and image_path:
        init_source_image(image_path)

    generators = {
        "gradient": generate_gradient_tile,
        "mandelbrot": generate_mandelbrot_tile,
        "checkerboard": generate_checkerboard_tile,
        "plasma": generate_plasma_tile,
        "noise": generate_noise_tile,
        "white": generate_white_tile,
        "atlas": lambda tx, ty: generate_atlas_tile(tx, ty, seed),
        "image": generate_image_tile,
    }

    gen_func = generators.get(pattern)
    if not gen_func:
        return []

    out = []
    for x, y in tiles:
        pixel_data = gen_func(x, y)
        if pixel_data is not None:
            out.append((x, y, pixel_data))
    return out


# =============================================================================
# Database Operations (FAST batch inserts)
# =============================================================================


async def save_tiles_batch(pool, tiles: list[tuple[int, int, bytes]]) -> int:
    """
    Save tiles using batch INSERT with unnest for maximum speed.

    This is ~100x faster than individual inserts.
    """
    if not tiles:
        return 0

    from app.config import settings

    # Prepare arrays for batch insert
    tile_ids = []
    chunk_ids = []
    pixel_data_list = []

    for x, y, pixel_data in tiles:
        tile_ids.append(f"{x}:{y}")
        chunk_ids.append(f"{x // settings.chunk_size}:{y // settings.chunk_size}")
        pixel_data_list.append(pixel_data)

    # Batch upsert using unnest (version and updated_at handled by ON CONFLICT)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO tiles (tile_id, chunk_id, pixel_data, version, updated_at)
            SELECT unnest($1::text[]), unnest($2::text[]), unnest($3::bytea[]), 1, NOW()
            ON CONFLICT (tile_id) DO UPDATE SET
                pixel_data = EXCLUDED.pixel_data,
                version = tiles.version + 1,
                updated_at = NOW()
        """,
            tile_ids,
            chunk_ids,
            pixel_data_list,
        )

    return len(tiles)


async def clear_tiles_batch(pool, x1: int, y1: int, x2: int, y2: int) -> int:
    """Clear all tiles in a region using efficient batch delete."""
    # Use range-based delete with LIKE pattern for efficiency
    async with pool.acquire() as conn:
        # For large regions, delete by chunk ranges
        result = await conn.execute(
            """
            DELETE FROM tiles 
            WHERE tile_id = ANY(
                SELECT format('%s:%s', x, y)
                FROM generate_series($1, $2 - 1) x,
                     generate_series($3, $4 - 1) y
            )
        """,
            x1,
            x2,
            y1,
            y2,
        )

        # Parse "DELETE N"
        if result and "DELETE" in result:
            return int(result.split()[1])
    return 0


# =============================================================================
# Earth: strip-at-a-time fill from the world-map plate
# =============================================================================


async def _fill_from_plate(
    pool, batch_size: int, seed: int, rows_per_strip: int = 8
) -> tuple[int, int]:
    """
    Fill the mosaic from the world-map plate. Returns (stored, seen).

    Imported here rather than at module scope: earth_map borrows this module's
    drawing primitives, so a top-level import either way round would cycle.

    This bypasses the ProcessPoolExecutor the procedural patterns use. The plate
    is drawn from a 233 Mpx DEM and ~100k projected vertices, and giving each of
    eight worker processes its own copy of that costs far more than the parallel
    generation saves -- while a 32 px window is too small to draw a vector into
    without losing the crispness that made vectors worth using.
    """
    import earth_map

    ok, why = earth_map.data_available()
    if not ok:
        raise FileNotFoundError(why)

    stored = 0
    seen = 0
    pending: list[tuple[int, int, bytes]] = []
    step = rows_per_strip * TILE_SIZE
    start = time.time()

    for y_px in range(0, GRID_HEIGHT * TILE_SIZE, step):
        y_end = min(y_px + step, GRID_HEIGHT * TILE_SIZE)
        strip = earth_map.render_strip(y_px, y_end, scale=1.0, seed=seed)

        for local_row in range(strip.shape[0] // TILE_SIZE):
            ty = (y_px // TILE_SIZE) + local_row
            row = strip[local_row * TILE_SIZE : (local_row + 1) * TILE_SIZE]

            # Cut the row into tiles in one reshape rather than a million slices,
            # and test blankness for the whole row at once.
            tiles = np.ascontiguousarray(
                row.reshape(TILE_SIZE, GRID_WIDTH, TILE_SIZE, 3).transpose(1, 0, 2, 3)
            )
            blank = (tiles == 255).all(axis=(1, 2, 3))
            seen += GRID_WIDTH

            for tx in np.nonzero(~blank)[0]:
                pending.append((int(tx), ty, tiles[tx].tobytes()))

            while len(pending) >= batch_size:
                stored += await save_tiles_batch(pool, pending[:batch_size])
                pending = pending[batch_size:]

        elapsed = time.time() - start
        pct = seen / (GRID_WIDTH * GRID_HEIGHT) * 100
        eta = (elapsed / max(pct, 0.01)) * (100 - pct)
        print(
            f"\rProgress: {pct:.1f}% ({seen:,}/{GRID_WIDTH * GRID_HEIGHT:,}) "
            f"- {seen / max(elapsed, 0.001):,.0f} tiles/sec - ETA: {eta:.0f}s",
            end="",
            flush=True,
        )

    if pending:
        stored += await save_tiles_batch(pool, pending)
    return stored, seen


async def _fill_from_world_plate(
    pool, batch_size: int, region_tiles: int = 100
) -> tuple[int, int]:
    """
    Fill the mosaic from the layered-relief world map. Returns (stored, seen).

    Imported lazily to keep the world-map data and its 233 Mpx bathymetry out of
    the process unless this pattern is actually asked for.

    Unlike the line-art patterns, this one colours the ocean, so effectively no
    tile is blank and all million are stored. Flat colour bands compress well in
    Postgres, but the row count is the full grid either way.
    """
    import world_map

    ok, why = world_map.data_available()
    if not ok:
        raise FileNotFoundError(why)

    print("Collision audit: " + ", ".join(world_map.audit_collisions()))
    print(
        "Stretch: "
        + ", ".join(
            f"{lat}deg={world_map.stretch_at(float(lat)):.2f}x"
            for lat in (0, 35, 50, 80)
        )
    )
    print()

    stored = 0
    seen = 0
    pending: list[tuple[int, int, bytes]] = []
    start = time.time()

    for ty, tiles in world_map.iter_tile_rows(region_tiles=region_tiles):
        blank = (tiles == 255).all(axis=(1, 2, 3))
        seen += GRID_WIDTH
        for tx in np.nonzero(~blank)[0]:
            pending.append((int(tx), ty, tiles[tx].tobytes()))

        while len(pending) >= batch_size:
            stored += await save_tiles_batch(pool, pending[:batch_size])
            pending = pending[batch_size:]

        elapsed = time.time() - start
        pct = seen / (GRID_WIDTH * GRID_HEIGHT) * 100
        eta = (elapsed / max(pct, 0.01)) * (100 - pct)
        print(
            f"\rProgress: {pct:.1f}% ({seen:,}/{GRID_WIDTH * GRID_HEIGHT:,}) "
            f"- {seen / max(elapsed, 0.001):,.0f} tiles/sec - ETA: {eta:.0f}s",
            end="",
            flush=True,
        )

    if pending:
        stored += await save_tiles_batch(pool, pending)
    return stored, seen


# =============================================================================
# Main Script
# =============================================================================


async def init_mosaic(
    pattern: str,
    image_path: str | None = None,
    region: tuple[int, int, int, int] | None = None,
    sparse: float = 1.0,
    replace: bool = False,
    workers: int = NUM_WORKERS,
    batch_size: int = DB_BATCH_SIZE,
    seed: int = 1,
    region_tiles: int = 100,
) -> None:
    """Initialize the mosaic with the specified pattern."""
    import ssl as ssl_module

    import asyncpg
    from app.config import settings

    db_url = settings.database_url
    masked = db_url.split("@")[-1] if "@" in db_url else db_url
    print(f"Connecting to database: ...@{masked}")

    ssl_ctx = None
    if "rds.amazonaws.com" in db_url or "sslmode" in db_url:
        ssl_ctx = ssl_module.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl_module.CERT_NONE
        print("Using SSL for RDS connection")

    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        timeout=120,
        ssl=ssl_ctx,
    )

    try:
        # Determine region
        if region:
            x1, y1, x2, y2 = region
        else:
            x1, y1, x2, y2 = 0, 0, GRID_WIDTH, GRID_HEIGHT

        total_tiles = (x2 - x1) * (y2 - y1)

        # Clear existing tiles if requested
        if replace and pattern != "clear":
            print(f"Clearing existing tiles in region ({x1}, {y1}) to ({x2}, {y2})...")
            start_time = time.time()
            cleared = await clear_tiles_batch(pool, x1, y1, x2, y2)
            elapsed = time.time() - start_time
            print(
                f"Cleared {cleared:,} tiles in {elapsed:.1f}s "
                f"({cleared/max(elapsed,0.001):.0f} tiles/sec)"
            )
            print()

        print(f"Initializing mosaic with '{pattern}' pattern...")
        print(f"Region: ({x1}, {y1}) to ({x2}, {y2})")
        print(f"Total tiles: {total_tiles:,}")
        print(f"Workers: {workers}, DB batch size: {batch_size:,}")
        print()

        start_time = time.time()

        if pattern == "clear":
            cleared = await clear_tiles_batch(pool, x1, y1, x2, y2)
            elapsed = time.time() - start_time
            print(f"\nDone! Cleared {cleared:,} tiles in {elapsed:.1f}s")
            if elapsed > 0:
                print(f"Speed: {cleared / elapsed:,.0f} tiles/sec")
        elif pattern == "world":
            # One composed plate, always rendered whole.
            if region or sparse < 1.0:
                print("Note: --region and --sparse are ignored for 'world'.\n")
            stored, seen = await _fill_from_world_plate(
                pool, batch_size, region_tiles=region_tiles
            )
            elapsed = time.time() - start_time
            print(f"\n\nDone! Stored {stored:,} tiles in {elapsed:.1f}s")
            print(f"Speed: {seen / elapsed:,.0f} tiles/sec")
        elif pattern == "earth":
            # The plate is one composed drawing, not a field sampled per tile, so
            # it is always rendered whole; --region and --sparse do not apply.
            if region or sparse < 1.0:
                print("Note: --region and --sparse are ignored for 'earth'.\n")
            stored, seen = await _fill_from_plate(pool, batch_size, seed)
            elapsed = time.time() - start_time
            skipped = seen - stored
            print(f"\n\nDone! Stored {stored:,} tiles in {elapsed:.1f}s")
            print(f"Speed: {seen / elapsed:,.0f} tiles/sec")
            print(
                f"Skipped {skipped:,} blank tiles "
                f"({skipped / seen * 100:.0f}% of the plate left as paper)"
            )
        else:
            # Generate tile coordinate list
            tiles = []
            for y in range(y1, y2):
                for x in range(x1, x2):
                    if sparse < 1.0 and random.random() > sparse:
                        continue
                    tiles.append((x, y))

            if not tiles:
                print("No tiles to generate")
                return

            # Split into batches for parallel CPU processing
            cpu_batch_size = max(1000, len(tiles) // (workers * 2))
            cpu_batches = [
                tiles[i : i + cpu_batch_size]
                for i in range(0, len(tiles), cpu_batch_size)
            ]

            print(
                f"Generating {len(tiles):,} tiles in {len(cpu_batches)} CPU batches..."
            )
            print()

            tiles_created = 0
            tiles_seen = 0  # generated, whether or not they were worth storing
            pending_tiles = []

            # Process with multiprocessing for CPU-bound generation
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        process_tile_batch, (pattern, batch, image_path, seed)
                    ): len(batch)
                    for batch in cpu_batches
                }

                for future in as_completed(futures):
                    batch_results = future.result()
                    # Progress tracks tiles *generated*, not tiles stored: a
                    # pattern that skips blanks stores fewer than it makes, and
                    # counting inserts would leave the meter short of 100%.
                    tiles_seen += futures[future]
                    pending_tiles.extend(batch_results)

                    # Flush to database when we have enough
                    while len(pending_tiles) >= batch_size:
                        db_batch = pending_tiles[:batch_size]
                        pending_tiles = pending_tiles[batch_size:]
                        tiles_created += await save_tiles_batch(pool, db_batch)

                    # Progress update
                    pct = (tiles_seen / len(tiles)) * 100
                    elapsed = time.time() - start_time
                    rate = tiles_seen / elapsed if elapsed > 0 else 0
                    eta = (len(tiles) - tiles_seen) / rate if rate > 0 else 0
                    print(
                        f"\rProgress: {pct:.1f}% ({tiles_seen:,}/{len(tiles):,}) "
                        f"- {rate:,.0f} tiles/sec - ETA: {eta:.0f}s",
                        end="",
                        flush=True,
                    )

            # Flush remaining tiles
            if pending_tiles:
                tiles_created += await save_tiles_batch(pool, pending_tiles)

            elapsed = time.time() - start_time
            skipped = tiles_seen - tiles_created
            print(f"\n\nDone! Stored {tiles_created:,} tiles in {elapsed:.1f}s")
            print(f"Speed: {tiles_seen / elapsed:,.0f} tiles/sec")
            if skipped:
                print(
                    f"Skipped {skipped:,} blank tiles "
                    f"({skipped / tiles_seen * 100:.0f}% of the region left as paper)"
                )

        print()
        print("Note: Regenerate chunks with: python scripts/render_chunks.py")

    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(
        description="Initialize mosaic with a pattern (optimized)"
    )
    parser.add_argument(
        "--pattern",
        "-p",
        choices=[
            "gradient",
            "mandelbrot",
            "checkerboard",
            "plasma",
            "noise",
            "white",
            "atlas",
            "world",
            "earth",
            "image",
            "clear",
        ],
        default="gradient",
        help="Pattern to draw (default: gradient)",
    )
    parser.add_argument(
        "--region-tiles",
        type=int,
        default=100,
        help=(
            "Square render region for 'world', in tiles (default: 100). "
            "Peak memory scales with its square plus a full-width band; drop to "
            "40-50 on a small box. 100 needs roughly 1 GB."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Seed for generated patterns like atlas — changes the continent",
    )
    parser.add_argument(
        "--image-path", "-i", help="Path to source image (for image pattern)"
    )
    parser.add_argument(
        "--region",
        "-r",
        nargs=4,
        type=int,
        metavar=("X1", "Y1", "X2", "Y2"),
        help="Region to fill (default: entire mosaic)",
    )
    parser.add_argument(
        "--sparse",
        "-s",
        type=float,
        default=1.0,
        help="Sparsity (0-1, probability of filling each tile)",
    )
    parser.add_argument(
        "--replace", action="store_true", help="Clear existing tiles first"
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=NUM_WORKERS,
        help=f"Number of parallel workers (default: {NUM_WORKERS})",
    )
    parser.add_argument(
        "--batch-size",
        "-b",
        type=int,
        default=DB_BATCH_SIZE,
        help=f"Database batch size (default: {DB_BATCH_SIZE})",
    )

    args = parser.parse_args()

    # Update batch size if specified
    batch_size = args.batch_size

    region = tuple(args.region) if args.region else None

    asyncio.run(
        init_mosaic(
            pattern=args.pattern,
            image_path=args.image_path,
            region=region,
            sparse=args.sparse,
            replace=args.replace,
            workers=args.workers,
            batch_size=batch_size,
            seed=args.seed,
            region_tiles=args.region_tiles,
        )
    )


if __name__ == "__main__":
    main()
