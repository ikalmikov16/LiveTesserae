import time

from fastapi import APIRouter

from app.config import settings
from app.services.database import db

router = APIRouter()

# Simple in-memory cache for stats (avoid DB spam from landing page loads)
_stats_cache: dict = {"data": None, "expires_at": 0.0}
STATS_CACHE_TTL = 30  # seconds


@router.get("/mosaic/stats")
async def mosaic_stats():
    """
    Get mosaic statistics for the landing page.

    Returns tile count, total edits, unique editors, and pixels painted.
    Cached for 30 seconds to minimize DB load.
    """
    now = time.time()

    if _stats_cache["data"] and now < _stats_cache["expires_at"]:
        return _stats_cache["data"]

    edited_tiles = await db.fetchval("SELECT COUNT(*) FROM tiles") or 0
    total_edits = await db.fetchval("SELECT COUNT(*) FROM edit_log") or 0
    unique_editors = (
        await db.fetchval("SELECT COUNT(DISTINCT session_id) FROM edit_log") or 0
    )

    data = {
        "edited_tiles": edited_tiles,
        "total_edits": total_edits,
        "unique_editors": unique_editors,
        "pixels_painted": edited_tiles * 1024,  # 32×32 pixels per tile
    }

    _stats_cache["data"] = data
    _stats_cache["expires_at"] = now + STATS_CACHE_TTL

    return data


@router.get("/mosaic/info")
async def mosaic_info():
    """
    Get mosaic configuration and statistics.

    Returns grid dimensions, tile size, chunk configuration, and tile count.
    """
    # Get count of edited tiles
    tile_count = await db.fetchval("SELECT COUNT(*) FROM tiles") or 0

    return {
        "grid_width": settings.grid_width,
        "grid_height": settings.grid_height,
        "tile_size": settings.tile_size,
        "chunk_size": settings.chunk_size,
        "total_tiles": settings.grid_width * settings.grid_height,
        "total_chunks": (settings.grid_width // settings.chunk_size) ** 2,
        "edited_tiles": tile_count,
    }
