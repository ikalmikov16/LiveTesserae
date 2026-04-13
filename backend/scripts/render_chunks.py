#!/usr/bin/env python3
"""
Render all chunks and the mosaic overview.

Run this after init_mosaic.py to generate the Level 1 chunks and Level 0 overview.

OPTIMIZED:
- Uses concurrent asyncio tasks with semaphore for parallel chunk rendering
- Preloads tile data for each chunk to minimize DB round-trips
- Processes chunks in batches for better memory management

Usage:
    python scripts/render_chunks.py
    python scripts/render_chunks.py --chunks-only  # Skip overview
    python scripts/render_chunks.py --overview-only  # Skip chunks
    python scripts/render_chunks.py --workers 8  # Concurrent chunks
"""

import argparse
import asyncio
import io
import os
import ssl as ssl_module
import sys
import time
from pathlib import Path

# Add parent directory to path so we can import from app
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from PIL import Image

from app.services import storage
from app.config import settings


def _rds_ssl_context():
    """Create SSL context for RDS connections when needed."""
    db_url = settings.database_url
    if "rds.amazonaws.com" in db_url or "sslmode" in db_url:
        ctx = ssl_module.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl_module.CERT_NONE
        return ctx
    return None


# Number of concurrent chunk renders
DEFAULT_WORKERS = min(8, os.cpu_count() or 4)

# These MUST match backend/app/services/chunk_renderer.py
CHUNK_PREVIEW_SIZE = 2048  # pixels per chunk image (must match backend!)
MOSAIC_PREVIEW_SIZE = 5000  # pixels for full overview (must match backend!)


def rgb_bytes_to_image(pixel_data: bytes) -> Image.Image:
    """Convert 3072 bytes of RGB data to a PIL Image."""
    arr = np.frombuffer(pixel_data, dtype=np.uint8).reshape((32, 32, 3))
    return Image.fromarray(arr, mode="RGB")


def _get_tile_bounds_in_chunk(
    local_tx: int, local_ty: int
) -> tuple[int, int, int, int]:
    """
    Calculate exact pixel bounds for a tile within a chunk image.
    Must match chunk_renderer._get_tile_bounds_in_chunk exactly!
    """
    pixels_per_tile = CHUNK_PREVIEW_SIZE / settings.chunk_size  # 20.48

    x1 = round(local_tx * pixels_per_tile)
    y1 = round(local_ty * pixels_per_tile)
    x2 = round((local_tx + 1) * pixels_per_tile)
    y2 = round((local_ty + 1) * pixels_per_tile)

    return (x1, y1, x2 - x1, y2 - y1)


async def render_chunk_optimized(pool, cx: int, cy: int) -> bytes:
    """
    Render a chunk by fetching all its tile data in one query.

    Uses same rendering logic as chunk_renderer.py for consistency.
    """
    # Calculate tile range for this chunk
    start_x = cx * settings.chunk_size
    start_y = cy * settings.chunk_size
    end_x = start_x + settings.chunk_size
    end_y = start_y + settings.chunk_size

    # Fetch all tiles for this chunk in one query
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT tile_id, pixel_data 
            FROM tiles 
            WHERE tile_id = ANY(
                SELECT format('%s:%s', x, y)
                FROM generate_series($1, $2 - 1) x,
                     generate_series($3, $4 - 1) y
            )
        """,
            start_x,
            end_x,
            start_y,
            end_y,
        )

    # Build tile data map
    tile_data = {}
    for row in rows:
        tile_data[row["tile_id"]] = row["pixel_data"]

    # Create chunk image at CHUNK_PREVIEW_SIZE (2048×2048)
    chunk_img = Image.new(
        "RGB", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), (255, 255, 255)
    )

    # Paste tiles with proper bounds (matching chunk_renderer.py exactly)
    for local_ty in range(settings.chunk_size):
        for local_tx in range(settings.chunk_size):
            tile_x = start_x + local_tx
            tile_y = start_y + local_ty
            tile_id = f"{tile_x}:{tile_y}"

            if tile_id in tile_data and tile_data[tile_id]:
                tile_img = rgb_bytes_to_image(tile_data[tile_id])

                # Get exact bounds for this tile (same as chunk_renderer)
                px, py, tw, th = _get_tile_bounds_in_chunk(local_tx, local_ty)
                tile_img = tile_img.resize((tw, th), Image.Resampling.LANCZOS)
                chunk_img.paste(tile_img, (px, py))

    # Convert to WebP (same quality as backend)
    buffer = io.BytesIO()
    chunk_img.save(buffer, format="WEBP", quality=90)
    return buffer.getvalue()


async def render_chunk_task(
    pool, cx: int, cy: int, semaphore: asyncio.Semaphore
) -> tuple[int, int, bool]:
    """Render a single chunk with semaphore for concurrency control."""
    async with semaphore:
        chunk_data = await render_chunk_optimized(pool, cx, cy)
        await storage.save_chunk_image(cx, cy, chunk_data)
        return (cx, cy, True)


async def render_all_chunks(
    workers: int = DEFAULT_WORKERS, skip_existing: bool = False
) -> int:
    """Render all chunk preview images with concurrent processing."""
    import asyncpg

    chunks_per_row = settings.grid_width // settings.chunk_size
    total_chunks = chunks_per_row * chunks_per_row

    print(f"Rendering {total_chunks} chunks with {workers} concurrent workers...")
    print()

    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=workers,
        max_size=workers * 2,
        timeout=120,
        ssl=_rds_ssl_context(),
    )

    try:
        start_time = time.time()
        semaphore = asyncio.Semaphore(workers)

        # Build list of chunks to render
        chunks_to_render = []
        for cy in range(chunks_per_row):
            for cx in range(chunks_per_row):
                if skip_existing:
                    existing = await storage.get_chunk_image(cx, cy)
                    if existing:
                        continue
                chunks_to_render.append((cx, cy))

        if not chunks_to_render:
            print("No chunks to render.")
            return 0

        # Create all tasks
        tasks = [
            render_chunk_task(pool, cx, cy, semaphore) for cx, cy in chunks_to_render
        ]

        # Run with progress tracking
        rendered = 0
        for coro in asyncio.as_completed(tasks):
            cx, cy, success = await coro
            rendered += 1

            elapsed = time.time() - start_time
            rate = rendered / elapsed if elapsed > 0 else 0
            eta = (len(chunks_to_render) - rendered) / rate if rate > 0 else 0
            pct = (rendered / len(chunks_to_render)) * 100

            print(
                f"\rProgress: {pct:.0f}% ({rendered}/{len(chunks_to_render)}) "
                f"- {rate:.1f} chunks/sec - ETA: {eta:.0f}s",
                end="",
                flush=True,
            )

        elapsed = time.time() - start_time
        print(
            f"\n\nRendered {rendered} chunks in {elapsed:.1f}s ({rendered/elapsed:.1f} chunks/sec)"
        )
        return rendered

    finally:
        await pool.close()


async def render_overview_optimized(pool) -> bytes:
    """
    Render the mosaic overview by compositing all chunk images.

    Uses same logic as chunk_renderer.py for consistency.
    """
    chunks_per_row = settings.grid_width // settings.chunk_size  # 10
    pixels_per_chunk = MOSAIC_PREVIEW_SIZE / chunks_per_row  # 500

    overview_img = Image.new(
        "RGB", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255)
    )

    # Load and composite all chunks (with same bounds calculation as backend)
    for cy in range(chunks_per_row):
        for cx in range(chunks_per_row):
            chunk_data = await storage.get_chunk_image(cx, cy)
            if chunk_data:
                chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGB")

                # Calculate exact bounds (same as chunk_renderer._get_chunk_bounds_in_overview)
                x1 = round(cx * pixels_per_chunk)
                y1 = round(cy * pixels_per_chunk)
                x2 = round((cx + 1) * pixels_per_chunk)
                y2 = round((cy + 1) * pixels_per_chunk)

                chunk_img = chunk_img.resize(
                    (x2 - x1, y2 - y1), Image.Resampling.LANCZOS
                )
                overview_img.paste(chunk_img, (x1, y1))

    # Convert to WebP
    buffer = io.BytesIO()
    overview_img.save(buffer, format="WEBP", quality=90)
    return buffer.getvalue()


async def render_overview() -> None:
    """Render the mosaic overview image."""
    import asyncpg

    print("Rendering mosaic overview...")
    start_time = time.time()

    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=1,
        max_size=2,
        timeout=120,
        ssl=_rds_ssl_context(),
    )

    try:
        overview_data = await render_overview_optimized(pool)
        await storage.save_mosaic_overview(overview_data)

        elapsed = time.time() - start_time
        size_kb = len(overview_data) / 1024

        print(f"Overview rendered: {size_kb:.0f} KB in {elapsed:.1f}s")

    finally:
        await pool.close()


async def main(
    chunks_only: bool = False,
    overview_only: bool = False,
    workers: int = DEFAULT_WORKERS,
):
    """Main entry point."""
    storage.ensure_storage_directories()

    if not overview_only:
        await render_all_chunks(workers=workers)
        print()

    if not chunks_only:
        await render_overview()

    print()
    print("Done! Refresh your browser to see the changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render chunks and overview (optimized)"
    )
    parser.add_argument("--chunks-only", action="store_true", help="Only render chunks")
    parser.add_argument(
        "--overview-only", action="store_true", help="Only render overview"
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of concurrent chunk renders (default: {DEFAULT_WORKERS})",
    )
    parser.add_argument(
        "--skip-existing", action="store_true", help="Skip chunks that already exist"
    )

    args = parser.parse_args()

    asyncio.run(
        main(
            chunks_only=args.chunks_only,
            overview_only=args.overview_only,
            workers=args.workers,
        )
    )
