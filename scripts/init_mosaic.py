#!/usr/bin/env python3
"""
Initialize the mosaic with pre-generated tiles.

This script can draw various patterns across the entire mosaic canvas.
It writes tiles directly to storage for efficiency, then triggers chunk rendering.

OPTIMIZED VERSION: Uses numpy for fast pattern generation and multiprocessing
for parallel tile creation. ~10-50x faster than pixel-by-pixel approach.

Usage:
    python scripts/init_mosaic.py --pattern gradient
    python scripts/init_mosaic.py --pattern mandelbrot
    python scripts/init_mosaic.py --pattern checkerboard
    python scripts/init_mosaic.py --pattern plasma
    python scripts/init_mosaic.py --pattern image --image-path photo.jpg
    python scripts/init_mosaic.py --pattern clear  # Remove all tiles
"""

import argparse
import math
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

# Add parent directory to path so we can import from backend
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import numpy as np
from PIL import Image

# Configuration - should match backend settings
GRID_WIDTH = 1000
GRID_HEIGHT = 1000
TILE_SIZE = 32
CHUNK_SIZE = 100
# Backend storage is in backend/storage/ (relative to backend working directory)
STORAGE_PATH = Path(__file__).parent.parent / "backend" / "storage"
TILES_PATH = STORAGE_PATH / "tiles"
CHUNKS_PATH = STORAGE_PATH / "chunks"

# Number of parallel workers (use most CPUs but leave some for system)
NUM_WORKERS = max(1, os.cpu_count() - 2)


def get_tile_path(x: int, y: int) -> Path:
    """Get hierarchical path for a tile image."""
    cx, cy = x // CHUNK_SIZE, y // CHUNK_SIZE
    return TILES_PATH / str(cx) / str(cy) / f"{x}_{y}.png"


def save_tile(x: int, y: int, img: Image.Image) -> None:
    """Save a tile image to storage."""
    path = get_tile_path(x, y)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG", optimize=False)  # Skip optimize for speed


def clear_tile(x: int, y: int) -> bool:
    """Delete a tile from storage."""
    path = get_tile_path(x, y)
    if path.exists():
        path.unlink()
        return True
    return False


# =============================================================================
# Vectorized Pattern Generators (using numpy for speed)
# =============================================================================


def generate_gradient_tile(x: int, y: int) -> Image.Image:
    """Generate a rainbow gradient tile using numpy (vectorized)."""
    # Create coordinate grids for the tile
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)
    
    # Calculate hue for each pixel
    base_hue = (x / GRID_WIDTH + y / GRID_HEIGHT) / 2
    local_offset = (px_grid / TILE_SIZE / GRID_WIDTH + py_grid / TILE_SIZE / GRID_HEIGHT) / 2
    hue = (base_hue + local_offset) % 1.0
    
    # Convert HSV to RGB (vectorized)
    sat = 0.8
    val = 0.9
    
    # HSV to RGB conversion
    c = val * sat
    h_prime = hue * 6
    x_val = c * (1 - np.abs(h_prime % 2 - 1))
    
    # Initialize RGB arrays
    r = np.zeros_like(hue)
    g = np.zeros_like(hue)
    b = np.zeros_like(hue)
    
    # Handle each hue sector
    mask = (h_prime >= 0) & (h_prime < 1)
    r[mask], g[mask], b[mask] = c, x_val[mask], 0
    mask = (h_prime >= 1) & (h_prime < 2)
    r[mask], g[mask], b[mask] = x_val[mask], c, 0
    mask = (h_prime >= 2) & (h_prime < 3)
    r[mask], g[mask], b[mask] = 0, c, x_val[mask]
    mask = (h_prime >= 3) & (h_prime < 4)
    r[mask], g[mask], b[mask] = 0, x_val[mask], c
    mask = (h_prime >= 4) & (h_prime < 5)
    r[mask], g[mask], b[mask] = x_val[mask], 0, c
    mask = (h_prime >= 5) & (h_prime < 6)
    r[mask], g[mask], b[mask] = c, 0, x_val[mask]
    
    m = val - c
    r, g, b = r + m, g + m, b + m
    
    # Stack into RGBA array
    rgba = np.stack([
        (r * 255).astype(np.uint8),
        (g * 255).astype(np.uint8),
        (b * 255).astype(np.uint8),
        np.full((TILE_SIZE, TILE_SIZE), 255, dtype=np.uint8)
    ], axis=-1)
    
    return Image.fromarray(rgba, mode="RGBA")


def hsv_to_rgb_vectorized(h: np.ndarray, s: float, v: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
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


def generate_mandelbrot_tile(x: int, y: int, max_iter: int = 100) -> Image.Image:
    """Generate a Mandelbrot fractal tile using numpy (vectorized)."""
    # Create coordinate grids
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)
    
    # Map to complex plane
    real_min, real_max = -2.5, 1.0
    imag_min, imag_max = -1.2, 1.2
    
    mosaic_x = (x * TILE_SIZE + px_grid) / (GRID_WIDTH * TILE_SIZE)
    mosaic_y = (y * TILE_SIZE + py_grid) / (GRID_HEIGHT * TILE_SIZE)
    
    c_real = real_min + mosaic_x * (real_max - real_min)
    c_imag = imag_min + mosaic_y * (imag_max - imag_min)
    c = c_real + 1j * c_imag
    
    # Mandelbrot iteration (vectorized)
    z = np.zeros_like(c)
    iterations = np.zeros((TILE_SIZE, TILE_SIZE), dtype=np.int32)
    mask = np.ones((TILE_SIZE, TILE_SIZE), dtype=bool)
    
    for i in range(max_iter):
        z[mask] = z[mask] * z[mask] + c[mask]
        escaped = np.abs(z) > 2
        iterations[mask & escaped] = i
        mask = mask & ~escaped
    
    iterations[mask] = max_iter  # Points that never escaped
    
    # Color based on iterations
    in_set = iterations == max_iter
    hue = (iterations / max_iter) % 1.0
    
    r, g, b = hsv_to_rgb_vectorized(hue, 0.9, 0.9)
    
    # Black for points in set
    r[in_set] = 0
    g[in_set] = 0
    b[in_set] = 0
    
    rgba = np.stack([
        (r * 255).astype(np.uint8),
        (g * 255).astype(np.uint8),
        (b * 255).astype(np.uint8),
        np.full((TILE_SIZE, TILE_SIZE), 255, dtype=np.uint8)
    ], axis=-1)
    
    return Image.fromarray(rgba, mode="RGBA")


def generate_checkerboard_tile(x: int, y: int, square_size: int = 4) -> Image.Image:
    """Generate a checkerboard pattern tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)
    
    global_x = x * TILE_SIZE + px_grid
    global_y = y * TILE_SIZE + py_grid
    square_x = global_x // square_size
    square_y = global_y // square_size
    
    is_dark = (square_x + square_y) % 2 == 0
    
    rgba = np.zeros((TILE_SIZE, TILE_SIZE, 4), dtype=np.uint8)
    rgba[is_dark] = [50, 50, 50, 255]
    rgba[~is_dark] = [205, 205, 205, 255]
    
    return Image.fromarray(rgba, mode="RGBA")


def generate_plasma_tile(x: int, y: int, time_val: float = 0) -> Image.Image:
    """Generate a plasma effect tile using numpy (vectorized)."""
    px = np.arange(TILE_SIZE)
    py = np.arange(TILE_SIZE)
    px_grid, py_grid = np.meshgrid(px, py)
    
    gx = (x * TILE_SIZE + px_grid) / 50.0
    gy = (y * TILE_SIZE + py_grid) / 50.0
    
    v1 = np.sin(gx + time_val)
    v2 = np.sin(gy + time_val)
    v3 = np.sin((gx + gy) / 2 + time_val)
    v4 = np.sin(np.sqrt(gx * gx + gy * gy) + time_val)
    
    v = (v1 + v2 + v3 + v4) / 4.0
    hue = (v + 1) / 2
    
    r, g, b = hsv_to_rgb_vectorized(hue, 0.8, 0.9)
    
    rgba = np.stack([
        (r * 255).astype(np.uint8),
        (g * 255).astype(np.uint8),
        (b * 255).astype(np.uint8),
        np.full((TILE_SIZE, TILE_SIZE), 255, dtype=np.uint8)
    ], axis=-1)
    
    return Image.fromarray(rgba, mode="RGBA")


def generate_noise_tile(x: int, y: int) -> Image.Image:
    """Generate a random noise tile using numpy (vectorized)."""
    base_hue = ((x * 17 + y * 31) % 256) / 256.0
    
    hue = (base_hue + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.1) % 1.0
    sat = 0.5 + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.3
    val = 0.7 + np.random.random((TILE_SIZE, TILE_SIZE)) * 0.3
    
    # Simplified HSV to RGB for varying s/v
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
    
    r, g, b = r + m, g + m, b + m
    
    rgba = np.stack([
        (r * 255).astype(np.uint8),
        (g * 255).astype(np.uint8),
        (b * 255).astype(np.uint8),
        np.full((TILE_SIZE, TILE_SIZE), 255, dtype=np.uint8)
    ], axis=-1)
    
    return Image.fromarray(rgba, mode="RGBA")


# Pre-scaled source image for image pattern (set by main process)
_source_image_array: np.ndarray | None = None


def init_source_image(image_path: str) -> None:
    """Load and prepare source image for multiprocessing."""
    global _source_image_array
    img = Image.open(image_path).convert("RGBA")
    # Scale to mosaic size for easy slicing
    img = img.resize((GRID_WIDTH * TILE_SIZE, GRID_HEIGHT * TILE_SIZE), Image.Resampling.LANCZOS)
    _source_image_array = np.array(img)


def generate_image_tile(x: int, y: int) -> Image.Image:
    """Generate a tile from the pre-loaded source image."""
    global _source_image_array
    if _source_image_array is None:
        raise ValueError("Source image not initialized")
    
    # Extract the tile region
    start_x = x * TILE_SIZE
    start_y = y * TILE_SIZE
    tile_array = _source_image_array[start_y:start_y + TILE_SIZE, start_x:start_x + TILE_SIZE]
    
    return Image.fromarray(tile_array, mode="RGBA")


# =============================================================================
# Parallel Processing
# =============================================================================


def process_tile_batch(args: tuple) -> int:
    """Process a batch of tiles. Called by worker processes."""
    pattern, tiles, image_path = args
    
    # Initialize source image in worker if needed
    if pattern == "image" and image_path:
        init_source_image(image_path)
    
    created = 0
    for x, y in tiles:
        if pattern == "gradient":
            tile = generate_gradient_tile(x, y)
        elif pattern == "mandelbrot":
            tile = generate_mandelbrot_tile(x, y)
        elif pattern == "checkerboard":
            tile = generate_checkerboard_tile(x, y)
        elif pattern == "plasma":
            tile = generate_plasma_tile(x, y)
        elif pattern == "noise":
            tile = generate_noise_tile(x, y)
        elif pattern == "image":
            tile = generate_image_tile(x, y)
        else:
            continue
        
        save_tile(x, y, tile)
        created += 1
    
    return created


def clear_tile_batch(tiles: list[tuple[int, int]]) -> int:
    """Clear a batch of tiles."""
    deleted = 0
    for x, y in tiles:
        if clear_tile(x, y):
            deleted += 1
    return deleted


# =============================================================================
# Main Script
# =============================================================================


def clear_region(x1: int, y1: int, x2: int, y2: int, num_workers: int = NUM_WORKERS) -> int:
    """Clear all tiles in a region using parallel processing."""
    tiles = [(x, y) for y in range(y1, y2) for x in range(x1, x2)]
    
    if not tiles:
        return 0
    
    # Split into batches for parallel processing
    batch_size = max(1000, len(tiles) // num_workers)
    batches = [tiles[i:i + batch_size] for i in range(0, len(tiles), batch_size)]
    
    deleted = 0
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(clear_tile_batch, batch) for batch in batches]
        for future in as_completed(futures):
            deleted += future.result()
    
    return deleted


def init_mosaic(pattern: str, image_path: str | None = None, 
                region: tuple[int, int, int, int] | None = None,
                sparse: float = 1.0,
                replace: bool = False,
                workers: int = NUM_WORKERS) -> None:
    """
    Initialize the mosaic with the specified pattern using parallel processing.
    """
    num_workers = workers
    # Determine region to fill
    if region:
        x1, y1, x2, y2 = region
    else:
        x1, y1, x2, y2 = 0, 0, GRID_WIDTH, GRID_HEIGHT
    
    total_tiles = (x2 - x1) * (y2 - y1)
    
    # Clear tiles in the region first if --replace is set
    if replace and pattern != "clear":
        print(f"Clearing existing tiles in region ({x1}, {y1}) to ({x2}, {y2})...")
        start_time = time.time()
        cleared = clear_region(x1, y1, x2, y2, num_workers)
        elapsed = time.time() - start_time
        if cleared > 0:
            print(f"Cleared {cleared:,} existing tiles in {elapsed:.1f}s.")
        else:
            print(f"No existing tiles to clear ({elapsed:.1f}s).")
        print()
    
    print(f"Initializing mosaic with '{pattern}' pattern...")
    print(f"Region: ({x1}, {y1}) to ({x2}, {y2})")
    print(f"Total tiles: {total_tiles:,}")
    print(f"Using {num_workers} parallel workers")
    print()
    
    start_time = time.time()
    
    if pattern == "clear":
        # Clear mode
        tiles_cleared = clear_region(x1, y1, x2, y2, num_workers)
        elapsed = time.time() - start_time
        print(f"\nDone! Cleared {tiles_cleared:,} tiles in {elapsed:.1f}s.")
        print(f"Speed: {tiles_cleared / elapsed:.0f} tiles/sec")
    else:
        # Generate tiles list
        tiles = []
        for y in range(y1, y2):
            for x in range(x1, x2):
                if sparse < 1.0 and random.random() > sparse:
                    continue
                tiles.append((x, y))
        
        if not tiles:
            print("No tiles to generate (sparse=0?)")
            return
        
        # Split into batches for parallel processing
        # Use smaller batches for better progress reporting
        batch_size = max(500, len(tiles) // (num_workers * 4))
        batches = [tiles[i:i + batch_size] for i in range(0, len(tiles), batch_size)]
        
        print(f"Generating {len(tiles):,} tiles in {len(batches)} batches...")
        print()
        
        tiles_created = 0
        completed_batches = 0
        
        with ProcessPoolExecutor(max_workers=num_workers) as executor:
            # Submit all batches
            futures = {
                executor.submit(process_tile_batch, (pattern, batch, image_path)): len(batch)
                for batch in batches
            }
            
            # Process results as they complete
            for future in as_completed(futures):
                batch_created = future.result()
                tiles_created += batch_created
                completed_batches += 1
                
                # Progress update
                pct = (tiles_created / len(tiles)) * 100
                elapsed = time.time() - start_time
                rate = tiles_created / elapsed if elapsed > 0 else 0
                eta = (len(tiles) - tiles_created) / rate if rate > 0 else 0
                print(f"\rProgress: {pct:.1f}% ({tiles_created:,}/{len(tiles):,}) "
                      f"- {rate:.0f} tiles/sec - ETA: {eta:.0f}s", end="", flush=True)
        
        elapsed = time.time() - start_time
        print(f"\n\nDone! Created {tiles_created:,} tiles in {elapsed:.1f}s.")
        print(f"Speed: {tiles_created / elapsed:.0f} tiles/sec")
    
    print()
    print("Note: You'll need to regenerate chunks and overview.")
    print("Run: python scripts/render_chunks.py")


def main():
    parser = argparse.ArgumentParser(description="Initialize mosaic with a pattern (optimized)")
    parser.add_argument(
        "--pattern", "-p",
        choices=["gradient", "mandelbrot", "checkerboard", "plasma", "noise", "image", "clear"],
        default="gradient",
        help="Pattern to draw (default: gradient)"
    )
    parser.add_argument(
        "--image-path", "-i",
        help="Path to source image (for image pattern)"
    )
    parser.add_argument(
        "--region", "-r",
        nargs=4,
        type=int,
        metavar=("X1", "Y1", "X2", "Y2"),
        help="Region to fill (default: entire mosaic)"
    )
    parser.add_argument(
        "--sparse", "-s",
        type=float,
        default=1.0,
        help="Sparsity (0-1, probability of filling each tile)"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Clear existing tiles in the region before drawing"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=NUM_WORKERS,
        help=f"Number of parallel workers (default: {NUM_WORKERS})"
    )
    
    args = parser.parse_args()
    
    region = tuple(args.region) if args.region else None
    
    # Override worker count if specified
    workers = args.workers
    
    init_mosaic(
        pattern=args.pattern,
        image_path=args.image_path,
        region=region,
        sparse=args.sparse,
        replace=args.replace,
        workers=workers
    )


if __name__ == "__main__":
    main()
