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
    """Process a batch of tiles. Returns list of (x, y, pixel_data)."""
    pattern, tiles, image_path = args

    if pattern == "image" and image_path:
        init_source_image(image_path)

    generators = {
        "gradient": generate_gradient_tile,
        "mandelbrot": generate_mandelbrot_tile,
        "checkerboard": generate_checkerboard_tile,
        "plasma": generate_plasma_tile,
        "noise": generate_noise_tile,
        "white": generate_white_tile,
        "image": generate_image_tile,
    }

    gen_func = generators.get(pattern)
    if not gen_func:
        return []

    return [(x, y, gen_func(x, y)) for x, y in tiles]


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
            pending_tiles = []

            # Process with multiprocessing for CPU-bound generation
            with ProcessPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        process_tile_batch, (pattern, batch, image_path)
                    ): len(batch)
                    for batch in cpu_batches
                }

                for future in as_completed(futures):
                    batch_results = future.result()
                    pending_tiles.extend(batch_results)

                    # Flush to database when we have enough
                    while len(pending_tiles) >= batch_size:
                        db_batch = pending_tiles[:batch_size]
                        pending_tiles = pending_tiles[batch_size:]

                        saved = await save_tiles_batch(pool, db_batch)
                        tiles_created += saved

                        # Progress update
                        pct = (tiles_created / len(tiles)) * 100
                        elapsed = time.time() - start_time
                        rate = tiles_created / elapsed if elapsed > 0 else 0
                        eta = (len(tiles) - tiles_created) / rate if rate > 0 else 0
                        print(
                            f"\rProgress: {pct:.1f}% ({tiles_created:,}/{len(tiles):,}) "
                            f"- {rate:,.0f} tiles/sec - ETA: {eta:.0f}s",
                            end="",
                            flush=True,
                        )

            # Flush remaining tiles
            if pending_tiles:
                saved = await save_tiles_batch(pool, pending_tiles)
                tiles_created += saved

            elapsed = time.time() - start_time
            print(f"\n\nDone! Created {tiles_created:,} tiles in {elapsed:.1f}s")
            print(f"Speed: {tiles_created / elapsed:,.0f} tiles/sec")

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
            "image",
            "clear",
        ],
        default="gradient",
        help="Pattern to draw (default: gradient)",
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
        )
    )


if __name__ == "__main__":
    main()
