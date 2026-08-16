"""
Chunks API for multi-level rendering.

Provides endpoints to fetch:
- Individual chunk preview images (Level 1)
- Full mosaic overview image (Level 0)
- Version information for cache busting

IMPORTANT: Specific routes (like /overview) must be defined BEFORE
parameterized routes (like /{cx}/{cy}) to avoid routing conflicts.

Rendering policy: no request ever renders an image that already exists in
storage. A stale overview is served as-is and refreshed out of band, because
rendering it costs a full-size decode and a burst of landing-page loads after an
edit could hold several of those at once and exhaust the container. Renders only
happen in-request when there is nothing to serve at all, and even then only one
at a time process-wide.
"""

import asyncio
import logging

from fastapi import APIRouter, Response, HTTPException

from app.config import settings
from app.services import storage, chunk_renderer, overview

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chunks", tags=["chunks"])


# Single-flight state. Concurrent callers wanting the same image await one
# shared render instead of each starting their own.
_overview_render_task: asyncio.Task | None = None
_chunk_render_tasks: dict[tuple[int, int], asyncio.Task] = {}
_single_flight_lock = asyncio.Lock()


def _reset_render_state() -> None:
    """Clear single-flight state. Used by tests between cases."""
    global _overview_render_task
    _overview_render_task = None
    _chunk_render_tasks.clear()


async def _render_and_save_overview() -> bytes:
    """Render + persist the overview, holding the shared render permit."""
    async with chunk_renderer.render_semaphore:
        image_data = await chunk_renderer.render_mosaic_overview()
        await storage.save_mosaic_overview(image_data)
        return image_data


async def _render_and_save_chunk(cx: int, cy: int) -> bytes:
    """Render + persist one chunk, holding the shared render permit."""
    async with chunk_renderer.render_semaphore:
        image_data = await chunk_renderer.render_chunk(cx, cy)
        await storage.save_chunk_image(cx, cy, image_data)
        return image_data


async def _shielded(task: asyncio.Task) -> bytes:
    """
    Await a shared render without letting one caller cancel it for everyone.

    Starlette cancels the handler coroutine when its client disconnects.
    Awaiting the task directly propagates that cancellation into the task
    itself, so one abandoned request would abort the render that every other
    waiter is depending on.
    """
    return await asyncio.shield(task)


async def _overview_single_flight() -> bytes:
    global _overview_render_task

    async with _single_flight_lock:
        task = _overview_render_task
        if task is None or task.done():
            task = asyncio.create_task(_render_and_save_overview())
            _overview_render_task = task

    return await _shielded(task)


async def _chunk_single_flight(cx: int, cy: int) -> bytes:
    key = (cx, cy)

    async with _single_flight_lock:
        task = _chunk_render_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(_render_and_save_chunk(cx, cy))
            _chunk_render_tasks[key] = task

    return await _shielded(task)


# =============================================================================
# Overview routes (Level 0) - MUST come before parameterized routes
# =============================================================================


@router.get("/overview")
async def get_mosaic_overview():
    """
    Get full mosaic overview image (Level 0).

    Serves the cached image even when stale: one tile is 5x5 px at this scale,
    and clients are told to refetch by the overview_updated WebSocket
    broadcast. A missing image (first request after a deploy or a storage
    reset) is rendered on demand, once, however many clients ask at the time.
    """
    image_data = await storage.get_mosaic_overview()

    if image_data is None:
        logger.info("Overview not found, rendering for first time")
        try:
            image_data = await _overview_single_flight()
        except Exception as e:
            logger.error(f"Overview render failed: {e}")
            raise HTTPException(
                status_code=503, detail="Overview is being generated, retry shortly"
            )
    elif await storage.is_overview_stale():
        # Nudge the coalescer rather than rendering here. It rebuilds at most
        # once per window and owns the permit, so a burst of landing-page loads
        # cannot queue a full render each. Also self-heals the case where chunks
        # were rendered offline (init_mosaic.py / render_chunks.py --chunks-only)
        # and no tile save will ever arrive to rebuild the overview.
        overview.request_rebuild()

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

    Returns the cached image; rendering normally happens on tile save. A chunk
    with no image yet is rendered on demand — once per chunk, behind the shared
    render permit. Deployments should run scripts/render_chunks.py before
    opening traffic so a cold cache does not serialise 100 renders.
    """
    # Validate coordinates
    max_chunk = settings.grid_width // settings.chunk_size - 1
    if not (0 <= cx <= max_chunk and 0 <= cy <= max_chunk):
        raise HTTPException(status_code=400, detail="Chunk coordinates out of bounds")

    image_data = await storage.get_chunk_image(cx, cy)

    if not image_data:
        logger.debug(f"Chunk ({cx}, {cy}) not found, rendering")
        try:
            image_data = await _chunk_single_flight(cx, cy)
        except Exception as e:
            logger.error(f"Chunk ({cx}, {cy}) render failed: {e}")
            raise HTTPException(
                status_code=503, detail="Chunk is being generated, retry shortly"
            )

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
