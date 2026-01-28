"""
Chunk rendering service for multi-level pyramid.

Level 0: Mosaic overview (4000x4000) - 4 pixels per tile
Level 1: Chunk previews (1024x1024 each) - 10.24 pixels per tile
Level 2: Individual tiles (32x32 each) - handled separately
"""

import io
import logging

from PIL import Image

from app.config import settings
from app.services import storage

logger = logging.getLogger(__name__)

# Rendering sizes - high quality
CHUNK_PREVIEW_SIZE = 1024  # pixels per chunk image
MOSAIC_PREVIEW_SIZE = 4000  # pixels for full overview


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
        tile_data: PNG image data for the tile, or None to clear tile

    Returns:
        Updated WebP image data as bytes
    """
    # Load existing chunk image, or create new white one
    existing_chunk = await storage.get_chunk_image(cx, cy)
    if existing_chunk:
        chunk_img = Image.open(io.BytesIO(existing_chunk)).convert("RGBA")
    else:
        chunk_img = Image.new(
            "RGBA", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), (255, 255, 255, 255)
        )

    # Calculate tile position and size in chunk (with proper bounds to avoid gaps)
    local_tx = tx - cx * settings.chunk_size
    local_ty = ty - cy * settings.chunk_size
    px, py, tw, th = _get_tile_bounds_in_chunk(local_tx, local_ty)

    if tile_data:
        # Paste the updated tile
        tile_img = Image.open(io.BytesIO(tile_data)).convert("RGBA")
        tile_img = tile_img.resize((tw, th), Image.Resampling.LANCZOS)
        chunk_img.paste(tile_img, (px, py), tile_img)
    else:
        # Clear the tile (draw white rectangle)
        white = Image.new("RGBA", (tw, th), (255, 255, 255, 255))
        chunk_img.paste(white, (px, py))

    buffer = io.BytesIO()
    chunk_img.save(buffer, format="WEBP", quality=90)

    logger.debug(f"Updated tile ({tx}, {ty}) in chunk ({cx}, {cy})")

    return buffer.getvalue()


async def render_chunk(cx: int, cy: int) -> bytes:
    """
    Render a chunk by compositing all its tiles into a single 1024x1024 image.
    Use this for initial rendering or full re-renders (e.g., from init_mosaic script).
    For single tile updates, use update_chunk_tile() instead.

    Args:
        cx: Chunk X coordinate (0-9)
        cy: Chunk Y coordinate (0-9)

    Returns:
        WebP image data as bytes
    """
    chunk_img = Image.new(
        "RGBA", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), (255, 255, 255, 255)
    )

    start_x = cx * settings.chunk_size
    start_y = cy * settings.chunk_size

    tiles_rendered = 0

    for tx in range(start_x, min(start_x + settings.chunk_size, settings.grid_width)):
        for ty in range(
            start_y, min(start_y + settings.chunk_size, settings.grid_height)
        ):
            tile_data = await storage.get_tile_image(tx, ty)
            if tile_data:
                try:
                    tile_img = Image.open(io.BytesIO(tile_data)).convert("RGBA")
                    # Position in chunk preview with proper bounds
                    local_tx = tx - start_x
                    local_ty = ty - start_y
                    px, py, tw, th = _get_tile_bounds_in_chunk(local_tx, local_ty)
                    tile_img = tile_img.resize((tw, th), Image.Resampling.LANCZOS)
                    chunk_img.paste(tile_img, (px, py), tile_img)
                    tiles_rendered += 1
                except Exception as e:
                    logger.warning(
                        f"Failed to render tile ({tx}, {ty}) into chunk: {e}"
                    )

    buffer = io.BytesIO()
    chunk_img.save(buffer, format="WEBP", quality=90)

    logger.debug(f"Rendered chunk ({cx}, {cy}) with {tiles_rendered} tiles")

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
    # Load existing overview or create new white one
    existing_overview = await storage.get_mosaic_overview()
    if existing_overview:
        overview_img = Image.open(io.BytesIO(existing_overview)).convert("RGBA")
    else:
        overview_img = Image.new(
            "RGBA", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255, 255)
        )

    # Get exact bounds for this chunk in the overview
    px, py, cw, ch = _get_chunk_bounds_in_overview(cx, cy)

    # Paste the updated chunk
    chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGBA")
    chunk_img = chunk_img.resize((cw, ch), Image.Resampling.LANCZOS)
    overview_img.paste(chunk_img, (px, py))

    buffer = io.BytesIO()
    overview_img.save(buffer, format="WEBP", quality=90)

    logger.debug(f"Updated chunk ({cx}, {cy}) in overview")

    return buffer.getvalue()


async def render_mosaic_overview() -> bytes:
    """
    Render Level 0 by compositing all Level 1 chunk images into 4000x4000.
    Use this for initial rendering or full re-renders (e.g., from render_chunks.py).
    For single chunk updates, use update_overview_chunk() instead.

    Returns:
        WebP image data as bytes
    """
    mosaic_img = Image.new(
        "RGBA", (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE), (255, 255, 255, 255)
    )

    chunks_per_row = settings.grid_width // settings.chunk_size  # 10

    chunks_rendered = 0

    for cx in range(chunks_per_row):
        for cy in range(chunks_per_row):
            chunk_data = await storage.get_chunk_image(cx, cy)
            if chunk_data:
                try:
                    chunk_img = Image.open(io.BytesIO(chunk_data)).convert("RGBA")
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

    logger.debug(f"Rendered mosaic overview with {chunks_rendered} chunks")

    return buffer.getvalue()
