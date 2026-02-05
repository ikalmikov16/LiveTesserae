import asyncio
import logging
from datetime import datetime

from app.config import settings
from app.services.database import db
from app.services import storage
from app.services import chunk_renderer
from app.websocket.manager import manager

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

        # Broadcast chunk version update to subscribers
        chunk_id = f"{cx}:{cy}"
        await manager.broadcast_to_chunk(
            chunk_id,
            {
                "type": "chunk_updated",
                "cx": cx,
                "cy": cy,
                "version": chunk_version,
            },
        )

        # Update the overview (Level 0)
        overview_image_data = await chunk_renderer.update_overview_chunk(
            cx, cy, chunk_image_data
        )
        overview_version = await storage.save_mosaic_overview(overview_image_data)

        # Broadcast overview update to ALL connected clients
        await manager.broadcast(
            {
                "type": "overview_updated",
                "version": overview_version,
            }
        )

        logger.debug(
            f"Background: Updated chunk ({cx}, {cy}) v{chunk_version} and overview v{overview_version}"
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


async def save_tile(x: int, y: int, pixel_data: bytes) -> dict:
    """
    Save a tile from raw RGB pixel data.

    Args:
        x: Tile X coordinate (0-999)
        y: Tile Y coordinate (0-999)
        pixel_data: 3072 bytes of RGB data (32×32×3)

    Returns:
        Tile metadata dict
    """
    tile_id = calculate_tile_id(x, y)
    chunk_id = calculate_chunk_id(x, y)
    cx = x // settings.chunk_size
    cy = y // settings.chunk_size

    try:
        # Use transaction to ensure tile and chunk updates are atomic
        async with db.transaction() as conn:
            # Upsert tile with pixel_data
            row = await conn.fetchrow(
                """
                INSERT INTO tiles (tile_id, chunk_id, pixel_data, version, updated_at)
                VALUES ($1, $2, $3, 1, NOW())
                ON CONFLICT (tile_id) DO UPDATE SET
                    pixel_data = $3,
                    version = tiles.version + 1,
                    updated_at = NOW()
                RETURNING tile_id, chunk_id, version, updated_at
                """,
                tile_id,
                chunk_id,
                pixel_data,
            )

            # Update chunk tracking (in same transaction)
            await conn.execute(
                """
                INSERT INTO chunks (chunk_id, dirty, version)
                VALUES ($1, FALSE, 1)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    dirty = FALSE,
                    version = chunks.version + 1
                """,
                chunk_id,
            )

        # Background: update chunk and overview (after transaction commits)
        _schedule_background_task(_update_chunk_and_overview(cx, cy, x, y, pixel_data))

        logger.info(
            f"Saved tile {tile_id} (version {row['version']}), chunk update scheduled"
        )

    except Exception as e:
        logger.error(f"Database error saving tile {tile_id}: {e}")
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

    - Deletes tile record from database
    - Re-renders the chunk (Level 1) in background
    - Updates overview (Level 0) in background

    Returns deletion info, or None if tile didn't exist.
    """
    tile_id = calculate_tile_id(x, y)
    chunk_id = calculate_chunk_id(x, y)

    # Calculate chunk coordinates
    cx = x // settings.chunk_size
    cy = y // settings.chunk_size

    # Use transaction to ensure delete and chunk update are atomic
    async with db.transaction() as conn:
        # Delete from database
        result = await conn.execute(
            "DELETE FROM tiles WHERE tile_id = $1",
            tile_id,
        )

        # Update chunk if tile existed (in same transaction)
        if "DELETE 1" in result:
            await conn.execute(
                """
                INSERT INTO chunks (chunk_id, dirty, version)
                VALUES ($1, FALSE, 1)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    dirty = FALSE,
                    version = chunks.version + 1
                """,
                chunk_id,
            )

    # After transaction commits, schedule background updates
    if "DELETE 1" in result:
        _schedule_background_task(_update_chunk_and_overview(cx, cy, x, y, None))
        logger.info(f"Deleted tile {tile_id}, chunk update scheduled")

        return {
            "tile_id": tile_id,
            "chunk_id": chunk_id,
        }

    return None


async def get_tile_pixel_data(x: int, y: int) -> bytes | None:
    """
    Get tile RGB pixel data from database.

    Returns:
        3072 bytes of RGB data, or None if tile doesn't exist (default white)
    """
    tile_id = calculate_tile_id(x, y)

    result = await db.fetchval(
        "SELECT pixel_data FROM tiles WHERE tile_id = $1",
        tile_id,
    )

    return result


async def tile_exists(x: int, y: int) -> bool:
    """Check if a tile exists (is not default)."""
    tile_id = calculate_tile_id(x, y)
    result = await db.fetchval(
        "SELECT 1 FROM tiles WHERE tile_id = $1",
        tile_id,
    )
    return result is not None
