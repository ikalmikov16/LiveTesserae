"""
Chunk rendering service for multi-level pyramid.

Level 0: Mosaic overview (2048x2048) - 2.048 pixels per tile
Level 1: Chunk previews (2048x2048 each) - 20.48 pixels per tile
Level 2: Individual tiles (32x32 each) - stored as RGB bytes in database
"""

import asyncio
import io
import logging
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import numpy as np
from PIL import Image

from app.config import settings
from app.services import storage
from app.services.database import db

logger = logging.getLogger(__name__)

# Rendering sizes - high quality for smoother transitions between zoom levels
CHUNK_PREVIEW_SIZE = 2048  # pixels per chunk image (20.48 px/tile)
# The overview was 5000x5000 and its re-encode cost 1716 ms — 9.4x the chunk
# render, and the single biggest cost in a tile save. Zoom level 0 only engages
# below 3 px/tile, so the overview is never displayed wider than ~3000 px:
# 5000x5000 was ~2.8x more pixels than can ever reach a screen. Measured ~6x
# cheaper in CPU and bytes at 2048, with no visible quality loss.
MOSAIC_PREVIEW_SIZE = 2048  # pixels for full overview (2.048 px/tile)

# WebP encode settings, shared by every render path.
#
# method=0 is the fastest of libwebp's 0-6 effort levels: measured 1222 ms ->
# 473 ms on the old 5000x5000 overview, for roughly 40 KB more per image. Encode
# time is the whole bottleneck of this pipeline — both encodes in a tile save sit
# inside the single render permit below — so the trade is strongly worth it.
# Quality is unchanged; raise WEBP_METHOD if bytes ever matter more than latency.
WEBP_QUALITY = 90
WEBP_METHOD = 0

# Thread pool for CPU-bound PIL operations (prevents blocking the event loop)
_image_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="pil_worker")

# Serialises every image render in the process, for two independent reasons.
#
# Correctness: the critical section has to span read -> composite -> save.
# Releasing between the render call and the caller's save lets a second writer
# read the same pre-image and clobber the first writer's tile.
#
# Memory: a 2048x2048 RGB buffer is ~12.6 MB, and decode + resize + encode holds
# several at once. A 1 GB Fargate task cannot afford concurrent renders, so all
# render paths — the background task after a tile save, the coalesced overview
# rebuild, and the on-demand renders in the chunks API — share this one permit.
#
# MUST be acquired only at the OUTERMOST call site, never inside the render
# helpers below: asyncio.Semaphore is not reentrant, so a nested acquire
# deadlocks the process permanently (no timeout, no self-healing).
render_semaphore = asyncio.Semaphore(1)


def _encode_webp(img: Image.Image) -> bytes:
    """Encode a PIL image to WebP bytes with the shared settings."""
    buffer = io.BytesIO()
    img.save(buffer, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
    return buffer.getvalue()


def rgb_bytes_to_image(pixel_data: bytes) -> Image.Image:
    """
    Convert 3072 bytes of RGB data to a 32x32 PIL Image.

    Args:
        pixel_data: 3072 bytes (32×32×3 RGB, row-major order)

    Returns:
        32x32 PIL Image in RGB mode
    """
    # np.frombuffer gives a read-only view over the bytes, so copy before
    # handing it to PIL — Image.fromarray keeps a reference to the buffer and
    # downstream paste/resize expect a writable image.
    arr = np.frombuffer(pixel_data, dtype=np.uint8).reshape((32, 32, 3)).copy()
    return Image.fromarray(arr, mode="RGB")


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
    pixels_per_chunk = MOSAIC_PREVIEW_SIZE / chunks_per_row  # 204.8

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

    return _encode_webp(chunk_img)


async def load_or_render_chunk_image(cx: int, cy: int) -> bytes:
    """
    Return the stored chunk image, rebuilding it from the database if missing.

    Never let a caller composite onto fresh white when the image is absent:
    the chunk holds up to 10,000 tiles that only exist in Postgres, and saving
    a white-based composite erases every one of them from Levels 0 and 1 —
    permanently, because a chunk is only rebuilt when its image is *missing*
    and a wrong one now exists. Verified: 6 drawn tiles wiped by one unrelated
    edit against an empty image store, which is exactly a fresh deploy.

    The caller must already hold render_semaphore (the permit is not reentrant).
    """
    existing = await storage.get_chunk_image(cx, cy)
    if existing is not None:
        return existing

    logger.info(
        f"Chunk ({cx}, {cy}) image missing, rebuilding from database "
        "instead of compositing onto white"
    )
    return await render_chunk(cx, cy)


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
    # Load existing chunk from storage, or rebuild it from the database (async I/O)
    existing_chunk = await load_or_render_chunk_image(cx, cy)

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

    return _encode_webp(chunk_img), tiles_rendered


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


def _update_overview_chunks_sync(
    existing_overview: bytes | None,
    chunks: list[tuple[int, int, bytes]],
) -> bytes:
    """
    Synchronous PIL operations for update_overview_chunks.
    Runs in thread pool to avoid blocking the event loop.

    Pastes every chunk into one decode of the overview, so coalescing N dirty
    chunks costs one decode and one encode rather than N of each.
    """
    # Load existing overview or create new white one. Production callers go
    # through update_overview_chunks(), which never passes None — a missing
    # overview is fully re-rendered from the chunk images instead, or every
    # chunk that is not in this batch would be erased.
    if existing_overview:
        overview_img = Image.open(io.BytesIO(existing_overview)).convert("RGB")
    else:
        overview_img = Image.new(
            "RGB", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255)
        )

    for cx, cy, chunk_data in chunks:
        # Get exact bounds for this chunk in the overview
        px, py, cw, ch = _get_chunk_bounds_in_overview(cx, cy)

        # Paste the updated chunk
        chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGB")
        chunk_img = chunk_img.resize((cw, ch), Image.Resampling.LANCZOS)
        overview_img.paste(chunk_img, (px, py))

    return _encode_webp(overview_img)


def _update_overview_chunk_sync(
    existing_overview: bytes | None, cx: int, cy: int, chunk_data: bytes
) -> bytes:
    """Single-chunk form of _update_overview_chunks_sync."""
    return _update_overview_chunks_sync(existing_overview, [(cx, cy, chunk_data)])


async def update_overview_chunks(chunks: list[tuple[int, int, bytes]]) -> bytes:
    """
    Incrementally update a batch of chunks in the overview image.
    Much faster than re-rendering the entire overview.

    Falls back to a full re-render when no overview exists yet: pasting onto a
    fresh white image would erase every chunk outside this batch, the Level-0
    half of the cold-storage wipe (see load_or_render_chunk_image).

    Args:
        chunks: (cx, cy, WebP image data) for each chunk to paste

    Returns:
        Updated WebP image data as bytes
    """
    # Load existing overview from storage (async I/O)
    existing_overview = await storage.get_mosaic_overview()

    if existing_overview is None:
        logger.info(
            "Overview image missing, re-rendering from all chunks "
            "instead of compositing onto white"
        )
        return await render_mosaic_overview()

    # Run CPU-bound PIL operations in thread pool
    result = await run_in_thread(
        _update_overview_chunks_sync, existing_overview, chunks
    )

    logger.debug(f"Updated {len(chunks)} chunk(s) in overview")

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

    return _encode_webp(mosaic_img), chunks_rendered


async def render_mosaic_overview() -> bytes:
    """
    Render Level 0 by compositing all Level 1 chunk images into 2048x2048.
    Use this for initial rendering or full re-renders (e.g., from render_chunks.py).
    For incremental chunk updates, use update_overview_chunks() instead.

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
