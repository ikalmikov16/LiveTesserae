"""
Chunks API for multi-level rendering.

Provides endpoints to fetch:
- Individual chunk preview images (Level 1)
- Full mosaic overview image (Level 0)
- Version information for cache busting

IMPORTANT: Specific routes (like /overview) must be defined BEFORE
parameterized routes (like /{cx}/{cy}) to avoid routing conflicts.
"""

import logging

from fastapi import APIRouter, Response, HTTPException

from app.config import settings
from app.services import storage, chunk_renderer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chunks", tags=["chunks"])


# =============================================================================
# Overview routes (Level 0) - MUST come before parameterized routes
# =============================================================================


@router.get("/overview")
async def get_mosaic_overview():
    """
    Get full mosaic overview image (Level 0).

    Re-renders if stale (any chunk updated since last render).
    """
    if await storage.is_overview_stale():
        # Re-render overview from chunks
        logger.info("Overview is stale, re-rendering from chunks")
        image_data = await chunk_renderer.render_mosaic_overview()
        await storage.save_mosaic_overview(image_data)
    else:
        image_data = await storage.get_mosaic_overview()
        if not image_data:
            # First request ever, render the overview
            logger.info("Overview not found, rendering for first time")
            image_data = await chunk_renderer.render_mosaic_overview()
            await storage.save_mosaic_overview(image_data)

    version = await storage.get_overview_version()

    return Response(
        content=image_data,
        media_type="image/webp",
        headers={
            "Cache-Control": "no-cache, must-revalidate",
            "ETag": f'"overview_v{version}"',
        },
    )


@router.get("/overview/version")
async def get_overview_version_endpoint():
    """Get current version of overview and stale status."""
    version = await storage.get_overview_version()
    stale = await storage.is_overview_stale()
    return {"version": version, "stale": stale}


# =============================================================================
# Chunk routes (Level 1) - parameterized routes come after specific routes
# =============================================================================


@router.get("/{cx}/{cy}")
async def get_chunk(cx: int, cy: int):
    """
    Get chunk preview image (Level 1).

    Always returns cached image - rendering happens on tile save.
    If chunk doesn't exist (no tiles drawn), renders an empty white chunk.
    """
    # Validate coordinates
    max_chunk = settings.grid_width // settings.chunk_size - 1
    if not (0 <= cx <= max_chunk and 0 <= cy <= max_chunk):
        raise HTTPException(status_code=400, detail="Chunk coordinates out of bounds")

    image_data = await storage.get_chunk_image(cx, cy)

    if not image_data:
        # No tiles in this chunk yet - render an empty white chunk
        logger.debug(f"Chunk ({cx}, {cy}) not found, rendering empty chunk")
        image_data = await chunk_renderer.render_chunk(cx, cy)
        await storage.save_chunk_image(cx, cy, image_data)

    version = await storage.get_chunk_version(cx, cy)

    return Response(
        content=image_data,
        media_type="image/webp",
        headers={
            # Use version in URL for cache busting - but don't cache aggressively
            # This ensures browsers re-validate when version changes
            "Cache-Control": "no-cache, must-revalidate",
            "ETag": f'"{cx}_{cy}_v{version}"',
        },
    )


@router.get("/{cx}/{cy}/version")
async def get_chunk_version_endpoint(cx: int, cy: int):
    """Get current version of a chunk (for cache checking)."""
    # Validate coordinates
    max_chunk = settings.grid_width // settings.chunk_size - 1
    if not (0 <= cx <= max_chunk and 0 <= cy <= max_chunk):
        raise HTTPException(status_code=400, detail="Chunk coordinates out of bounds")

    version = await storage.get_chunk_version(cx, cy)
    return {"cx": cx, "cy": cy, "version": version}
