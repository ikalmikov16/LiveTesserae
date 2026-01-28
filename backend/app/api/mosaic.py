from fastapi import APIRouter

from app.config import settings
from app.services.database import db

router = APIRouter()


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
