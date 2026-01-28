import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.services.database import db
from app.services import storage
from app.services import chunk_renderer

logger = logging.getLogger(__name__)

# Track running background tasks to prevent premature garbage collection
_background_tasks: set[asyncio.Task] = set()


def calculate_tile_id(x: int, y: int) -> str:
    """Calculate tile ID from coordinates. Format: 'x:y'"""
    return f"{x}:{y}"


def calculate_chunk_id(x: int, y: int) -> str:
    """Calculate chunk ID from tile coordinates. Format: 'cx:cy'"""
    cx = x // settings.chunk_size
    cy = y // settings.chunk_size
    return f"{cx}:{cy}"


def parse_tile_id(tile_id: str) -> tuple[int, int]:
    """Parse tile ID back to coordinates."""
    x, y = tile_id.split(":")
    return int(x), int(y)


async def _update_chunk_and_overview(
    cx: int, cy: int, x: int, y: int, tile_data: bytes | None
) -> None:
    """
    Background task to update chunk and overview images after tile change.

    This runs asynchronously after the API response is sent, so users don't
    wait for image rendering. The tile data is already saved and visible
    at Level 2 immediately.
    """
    try:
        # Update the chunk (Level 1)
        chunk_image_data = await chunk_renderer.update_chunk_tile(
            cx, cy, x, y, tile_data
        )
        chunk_version = await storage.save_chunk_image(cx, cy, chunk_image_data)

        # Update the overview (Level 0)
        overview_image_data = await chunk_renderer.update_overview_chunk(
            cx, cy, chunk_image_data
        )
        await storage.save_mosaic_overview(overview_image_data)

        logger.debug(
            f"Background: Updated chunk ({cx}, {cy}) v{chunk_version} and overview"
        )

    except Exception as e:
        logger.error(f"Background chunk update failed for ({cx}, {cy}): {e}")


def _schedule_background_task(coro) -> None:
    """Schedule a background task and track it to prevent GC."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def get_tile_metadata(x: int, y: int) -> dict | None:
    """
    Get tile metadata from database.

    Returns None if tile doesn't exist (is default).
    """
    tile_id = calculate_tile_id(x, y)

    row = await db.fetchrow(
        """
        SELECT tile_id, chunk_id, version, updated_at
        FROM tiles
        WHERE tile_id = $1
        """,
        tile_id,
    )

    if row is None:
        return None

    return {
        "tile_id": row["tile_id"],
        "chunk_id": row["chunk_id"],
        "x": x,
        "y": y,
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


async def save_tile(x: int, y: int, image_data: bytes) -> dict:
    """
    Save a tile image, update database, and re-render chunk.

    - Saves image to filesystem
    - Upserts tile record in database
    - Increments version if tile already exists
    - Re-renders the chunk (Level 1) synchronously
    - Marks overview (Level 0) as stale

    Returns tile metadata including chunk version for cache busting.

    Note: If database write fails, the saved image is cleaned up to prevent orphan files.
    """
    tile_id = calculate_tile_id(x, y)
    chunk_id = calculate_chunk_id(x, y)

    # Calculate chunk coordinates
    cx = x // settings.chunk_size
    cy = y // settings.chunk_size

    # Save image to filesystem first
    await storage.save_tile_image(x, y, image_data)

    try:
        # Upsert tile record (insert or update)
        row = await db.fetchrow(
            """
            INSERT INTO tiles (tile_id, chunk_id, version, updated_at)
            VALUES ($1, $2, 1, NOW())
            ON CONFLICT (tile_id) DO UPDATE SET
                version = tiles.version + 1,
                updated_at = NOW()
            RETURNING tile_id, chunk_id, version, updated_at
            """,
            tile_id,
            chunk_id,
        )

        # Update chunk in DB (for tracking)
        await db.execute(
            """
            INSERT INTO chunks (chunk_id, dirty, version)
            VALUES ($1, FALSE, 1)
            ON CONFLICT (chunk_id) DO UPDATE SET
                dirty = FALSE,
                version = chunks.version + 1
            """,
            chunk_id,
        )

        # Fire and forget - update chunk and overview in background
        # This makes API response much faster (don't wait for image rendering)
        _schedule_background_task(_update_chunk_and_overview(cx, cy, x, y, image_data))

        logger.info(
            f"Saved tile {tile_id} (version {row['version']}), chunk update scheduled"
        )

    except Exception as e:
        # Clean up the saved image if database operation failed
        logger.error(f"Database error saving tile {tile_id}, cleaning up image: {e}")
        await storage.delete_tile_image(x, y)
        raise

    return {
        "tile_id": row["tile_id"],
        "chunk_id": row["chunk_id"],
        "x": x,
        "y": y,
        "version": row["version"],
        "updated_at": row["updated_at"],
    }


async def delete_tile(x: int, y: int) -> dict | None:
    """
    Delete a tile (reset to default) and re-render chunk.

    - Removes image from filesystem
    - Deletes tile record from database
    - Re-renders the chunk (Level 1) synchronously
    - Marks overview (Level 0) as stale

    Returns deletion info with chunk_version, or None if tile didn't exist.
    """
    tile_id = calculate_tile_id(x, y)
    chunk_id = calculate_chunk_id(x, y)

    # Calculate chunk coordinates
    cx = x // settings.chunk_size
    cy = y // settings.chunk_size

    # Delete from database
    result = await db.execute(
        "DELETE FROM tiles WHERE tile_id = $1",
        tile_id,
    )

    # Delete from filesystem
    await storage.delete_tile_image(x, y)

    # Update chunk if tile existed
    if "DELETE 1" in result:
        # Update chunk in DB
        await db.execute(
            """
            INSERT INTO chunks (chunk_id, dirty, version)
            VALUES ($1, FALSE, 1)
            ON CONFLICT (chunk_id) DO UPDATE SET
                dirty = FALSE,
                version = chunks.version + 1
            """,
            chunk_id,
        )

        # Fire and forget - update chunk and overview in background
        _schedule_background_task(_update_chunk_and_overview(cx, cy, x, y, None))

        logger.info(f"Deleted tile {tile_id}, chunk update scheduled")

        return {
            "tile_id": tile_id,
            "chunk_id": chunk_id,
        }

    return None


async def get_tile_image(x: int, y: int) -> bytes | None:
    """
    Get tile image data.

    Returns None if tile doesn't exist (is default).
    """
    return await storage.get_tile_image(x, y)


async def tile_exists(x: int, y: int) -> bool:
    """Check if a tile exists (is not default)."""
    tile_id = calculate_tile_id(x, y)
    result = await db.fetchval(
        "SELECT 1 FROM tiles WHERE tile_id = $1",
        tile_id,
    )
    return result is not None
