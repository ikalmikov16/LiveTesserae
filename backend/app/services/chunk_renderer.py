"""
Chunk rendering service for multi-level pyramid.

Level 0: Mosaic overview (5000x5000) - 5 pixels per tile
Level 1: Chunk previews (2048x2048 each) - 20.48 pixels per tile
Level 2: Individual tiles (32x32 each) - stored as RGB bytes in database
"""

import asyncio
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from PIL import Image

from app.config import settings
from app.services import storage
from app.services.database import db

logger = logging.getLogger(__name__)

# Rendering sizes - high quality for smoother transitions between zoom levels
CHUNK_PREVIEW_SIZE = 2048  # pixels per chunk image (20.48 px/tile)
MOSAIC_PREVIEW_SIZE = 5000  # pixels for full overview (5 px/tile)

# Thread pool for CPU-bound PIL operations (prevents blocking the event loop)
_image_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pil_worker")


def rgb_bytes_to_image(pixel_data: bytes) -> Image.Image:
    """
    Convert 3072 bytes of RGB data to a 32x32 PIL Image.

    Args:
        pixel_data: 3072 bytes (32×32×3 RGB, row-major order)

    Returns:
        32x32 PIL Image in RGB mode
    """
    img = Image.new("RGB", (32, 32))
    pixels = img.load()

    for i in range(1024):  # 32×32 = 1024 pixels
        x = i % 32
        y = i // 32
        idx = i * 3
        r, g, b = pixel_data[idx], pixel_data[idx + 1], pixel_data[idx + 2]
        pixels[x, y] = (r, g, b)

    return img


async def run_in_thread(func, *args, **kwargs):
    """Run a synchronous function in the thread pool to avoid blocking the event loop."""
    loop = asyncio.get_event_loop()
    if kwargs:
        func = partial(func, **kwargs)
    return await loop.run_in_executor(_image_executor, func, *args)


def _get_tile_bounds_in_chunk(
    local_tx: int, local_ty: int
) -> tuple[int, int, int, int]:
    """
    Calculate exact pixel bounds for a tile within a chunk image.
    Uses proper rounding to ensure tiles perfectly tile without gaps.

    Returns: (x, y, width, height)
    """
    # Calculate exact floating-point positions
    pixels_per_tile = CHUNK_PREVIEW_SIZE / settings.chunk_size  # 10.24

    x1 = round(local_tx * pixels_per_tile)
    y1 = round(local_ty * pixels_per_tile)
    x2 = round((local_tx + 1) * pixels_per_tile)
    y2 = round((local_ty + 1) * pixels_per_tile)

    return (x1, y1, x2 - x1, y2 - y1)


def _get_chunk_bounds_in_overview(cx: int, cy: int) -> tuple[int, int, int, int]:
    """
    Calculate exact pixel bounds for a chunk within the overview image.
    Uses proper rounding to ensure chunks perfectly tile without gaps.

    Returns: (x, y, width, height)
    """
    chunks_per_row = settings.grid_width // settings.chunk_size  # 10
    pixels_per_chunk = MOSAIC_PREVIEW_SIZE / chunks_per_row  # 400

    x1 = round(cx * pixels_per_chunk)
    y1 = round(cy * pixels_per_chunk)
    x2 = round((cx + 1) * pixels_per_chunk)
    y2 = round((cy + 1) * pixels_per_chunk)

    return (x1, y1, x2 - x1, y2 - y1)


def _update_chunk_tile_sync(
    existing_chunk: bytes | None,
    cx: int,
    cy: int,
    tx: int,
    ty: int,
    tile_data: bytes | None,
) -> bytes:
    """
    Synchronous PIL operations for update_chunk_tile.
    Runs in thread pool to avoid blocking the event loop.
    """
    # Load existing chunk image, or create new white one
    if existing_chunk:
        chunk_img = Image.open(io.BytesIO(existing_chunk)).convert("RGB")
    else:
        chunk_img = Image.new(
            "RGB", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), (255, 255, 255)
        )

    # Calculate tile position and size in chunk (with proper bounds to avoid gaps)
    local_tx = tx - cx * settings.chunk_size
    local_ty = ty - cy * settings.chunk_size
    px, py, tw, th = _get_tile_bounds_in_chunk(local_tx, local_ty)

    if tile_data:
        # Convert RGB bytes to image and paste
        tile_img = rgb_bytes_to_image(tile_data)
        tile_img = tile_img.resize((tw, th), Image.Resampling.LANCZOS)
        chunk_img.paste(tile_img, (px, py))
    else:
        # Clear the tile (draw white rectangle)
        white = Image.new("RGB", (tw, th), (255, 255, 255))
        chunk_img.paste(white, (px, py))

    buffer = io.BytesIO()
    chunk_img.save(buffer, format="WEBP", quality=90)

    return buffer.getvalue()


async def update_chunk_tile(
    cx: int, cy: int, tx: int, ty: int, tile_data: bytes | None
) -> bytes:
    """
    Incrementally update a single tile in a chunk image.
    Much faster than re-rendering the entire chunk.

    Args:
        cx: Chunk X coordinate
        cy: Chunk Y coordinate
        tx: Tile X coordinate (absolute)
        ty: Tile Y coordinate (absolute)
        tile_data: RGB pixel data (3072 bytes), or None to clear tile

    Returns:
        Updated WebP image data as bytes
    """
    # Load existing chunk from storage (async I/O)
    existing_chunk = await storage.get_chunk_image(cx, cy)

    # Run CPU-bound PIL operations in thread pool
    result = await run_in_thread(
        _update_chunk_tile_sync, existing_chunk, cx, cy, tx, ty, tile_data
    )

    logger.debug(f"Updated tile ({tx}, {ty}) in chunk ({cx}, {cy})")

    return result


def _render_chunk_sync(
    cx: int, cy: int, rows: list[dict], parse_tile_id_func
) -> tuple[bytes, int]:
    """
    Synchronous PIL operations for render_chunk.
    Runs in thread pool to avoid blocking the event loop.
    """
    chunk_img = Image.new(
        "RGB", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), (255, 255, 255)
    )

    start_x = cx * settings.chunk_size
    start_y = cy * settings.chunk_size

    tiles_rendered = 0

    for row in rows:
        pixel_data = row["pixel_data"]
        if pixel_data:
            try:
                tx, ty = parse_tile_id_func(row["tile_id"])
                tile_img = rgb_bytes_to_image(pixel_data)

                local_tx = tx - start_x
                local_ty = ty - start_y
                px, py, tw, th = _get_tile_bounds_in_chunk(local_tx, local_ty)

                tile_img = tile_img.resize((tw, th), Image.Resampling.LANCZOS)
                chunk_img.paste(tile_img, (px, py))
                tiles_rendered += 1
            except Exception as e:
                logger.warning(
                    f"Failed to render tile {row['tile_id']} into chunk: {e}"
                )

    buffer = io.BytesIO()
    chunk_img.save(buffer, format="WEBP", quality=90)

    return buffer.getvalue(), tiles_rendered


async def render_chunk(cx: int, cy: int) -> bytes:
    """
    Render a chunk by compositing all its tiles from database.
    Use this for initial rendering or full re-renders (e.g., from init_mosaic script).
    For single tile updates, use update_chunk_tile() instead.

    Args:
        cx: Chunk X coordinate (0-9)
        cy: Chunk Y coordinate (0-9)

    Returns:
        WebP image data as bytes
    """
    from app.services.tiles import parse_tile_id

    # Query all tiles in this chunk from database (async I/O)
    rows = await db.fetch(
        "SELECT tile_id, pixel_data FROM tiles WHERE chunk_id = $1",
        f"{cx}:{cy}",
    )

    # Convert asyncpg Records to dicts for thread pool
    rows_data = [
        {"tile_id": row["tile_id"], "pixel_data": row["pixel_data"]} for row in rows
    ]

    # Run CPU-bound PIL operations in thread pool
    result, tiles_rendered = await run_in_thread(
        _render_chunk_sync, cx, cy, rows_data, parse_tile_id
    )

    logger.debug(f"Rendered chunk ({cx}, {cy}) with {tiles_rendered} tiles")

    return result


def _update_overview_chunk_sync(
    existing_overview: bytes | None, cx: int, cy: int, chunk_data: bytes
) -> bytes:
    """
    Synchronous PIL operations for update_overview_chunk.
    Runs in thread pool to avoid blocking the event loop.
    """
    # Load existing overview or create new white one
    if existing_overview:
        overview_img = Image.open(io.BytesIO(existing_overview)).convert("RGB")
    else:
        overview_img = Image.new(
            "RGB", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255)
        )

    # Get exact bounds for this chunk in the overview
    px, py, cw, ch = _get_chunk_bounds_in_overview(cx, cy)

    # Paste the updated chunk
    chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGB")
    chunk_img = chunk_img.resize((cw, ch), Image.Resampling.LANCZOS)
    overview_img.paste(chunk_img, (px, py))

    buffer = io.BytesIO()
    overview_img.save(buffer, format="WEBP", quality=90)

    return buffer.getvalue()


async def update_overview_chunk(cx: int, cy: int, chunk_data: bytes) -> bytes:
    """
    Incrementally update a single chunk in the overview image.
    Much faster than re-rendering the entire overview.

    Args:
        cx: Chunk X coordinate
        cy: Chunk Y coordinate
        chunk_data: WebP image data for the chunk

    Returns:
        Updated WebP image data as bytes
    """
    # Load existing overview from storage (async I/O)
    existing_overview = await storage.get_mosaic_overview()

    # Run CPU-bound PIL operations in thread pool
    result = await run_in_thread(
        _update_overview_chunk_sync, existing_overview, cx, cy, chunk_data
    )

    logger.debug(f"Updated chunk ({cx}, {cy}) in overview")

    return result


def _render_mosaic_overview_sync(
    chunks_data: list[tuple[int, int, bytes | None]],
) -> tuple[bytes, int]:
    """
    Synchronous PIL operations for render_mosaic_overview.
    Runs in thread pool to avoid blocking the event loop.
    """
    mosaic_img = Image.new(
        "RGB", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255)
    )

    chunks_rendered = 0

    for cx, cy, chunk_data in chunks_data:
        if chunk_data:
            try:
                chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGB")
                # Get exact bounds for this chunk
                px, py, cw, ch = _get_chunk_bounds_in_overview(cx, cy)
                chunk_img = chunk_img.resize((cw, ch), Image.Resampling.LANCZOS)
                mosaic_img.paste(chunk_img, (px, py))
                chunks_rendered += 1
            except Exception as e:
                logger.warning(
                    f"Failed to render chunk ({cx}, {cy}) into overview: {e}"
                )

    buffer = io.BytesIO()
    mosaic_img.save(buffer, format="WEBP", quality=90)

    return buffer.getvalue(), chunks_rendered


async def render_mosaic_overview() -> bytes:
    """
    Render Level 0 by compositing all Level 1 chunk images into 5000x5000.
    Use this for initial rendering or full re-renders (e.g., from render_chunks.py).
    For single chunk updates, use update_overview_chunk() instead.

    Returns:
        WebP image data as bytes
    """
    chunks_per_row = settings.grid_width // settings.chunk_size  # 10

    # Load all chunks in parallel (async I/O)
    async def load_chunk(cx: int, cy: int) -> tuple[int, int, bytes | None]:
        data = await storage.get_chunk_image(cx, cy)
        return (cx, cy, data)

    # Create tasks for all chunks
    tasks = [
        load_chunk(cx, cy)
        for cx in range(chunks_per_row)
        for cy in range(chunks_per_row)
    ]

    # Load all chunks in parallel
    chunks_data = await asyncio.gather(*tasks)

    # Run CPU-bound PIL operations in thread pool
    result, chunks_rendered = await run_in_thread(
        _render_mosaic_overview_sync, chunks_data
    )

    logger.debug(f"Rendered mosaic overview with {chunks_rendered} chunks")

    return result
