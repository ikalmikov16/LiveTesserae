"""
Coalesced Level-0 overview rebuilds.

The overview used to be re-encoded inside *every* tile save, which is what
capped the whole site at ~0.5 saves/sec: five people drawing one tile each per
two seconds saw updates arrive 27 s after they stopped. The person drawing never
noticed (their PUT returns in ~20 ms); everyone else fell behind.

Here a tile save only re-renders its chunk and marks that chunk dirty. One
background loop rebuilds the overview at most once every
``settings.overview_coalesce_seconds``, pasting all chunks that went dirty in
that window into a single decode/encode. N saves in a window cost one overview
render instead of N.

Ordering rule that makes the dirty set safe (both halves matter):

* a chunk is marked dirty *after* its image is written and *while its writer
  still holds* ``render_semaphore``;
* this module reads the dirty set, composites, saves, and clears the flags all
  inside one hold of the same permit.

So a chunk image can never be written between the read and the clear, and the
set cleared is exactly the set composited. Clearing outside the permit would
silently drop any edit that landed in that gap.
"""

import asyncio
import logging

from app.config import settings
from app.services import chunk_renderer, storage
from app.services.database import db
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

# Set whenever there is work; the loop waits on it instead of polling.
_wake = asyncio.Event()

_loop_task: asyncio.Task | None = None

# Broadcasts scheduled outside the render permit, tracked so they survive GC
# and can be drained on shutdown and between tests.
_background_tasks: set[asyncio.Task] = set()


def _schedule_background_task(coro) -> None:
    """Schedule a background task and track it to prevent GC."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def request_rebuild() -> None:
    """Ask the loop to rebuild the overview on its next tick."""
    _wake.set()


async def mark_chunk_dirty(chunk_id: str) -> None:
    """
    Record that a chunk image changed and the overview no longer reflects it.

    Call this only from inside the render permit, after the chunk image has been
    written — see the ordering rule in the module docstring.
    """
    await db.execute(
        """
        INSERT INTO chunks (chunk_id, dirty, version)
        VALUES ($1, TRUE, 0)
        ON CONFLICT (chunk_id) DO UPDATE SET dirty = TRUE
        """,
        chunk_id,
    )
    request_rebuild()


async def _fetch_dirty_chunks() -> list[tuple[int, int]]:
    """Chunk coordinates whose images are newer than the overview."""
    rows = await db.fetch("SELECT chunk_id FROM chunks WHERE dirty = TRUE")
    coords = []
    for row in rows:
        cx, cy = row["chunk_id"].split(":")
        coords.append((int(cx), int(cy)))
    return coords


async def _needs_full_rebuild() -> bool:
    """
    Whether a from-scratch composite is warranted.

    Requires both a stale flag and at least one chunk that has actually been
    rendered: on a virgin store every chunk image is missing, and compositing
    100 absent chunks just burns a render to produce a blank overview.
    """
    versions = await storage.load_chunk_versions()
    return bool(versions.get("overview_stale", True)) and bool(versions.get("chunks"))


async def flush_pending() -> bool:
    """
    Rebuild the overview once, now, if anything is pending.

    Returns True if the overview was re-rendered. Safe to call directly (tests
    and shutdown do); the loop is not required to be running.
    """
    # Cheap pre-check outside the permit so an idle loop never queues behind a
    # render just to discover there is nothing to do.
    if not await _fetch_dirty_chunks() and not await _needs_full_rebuild():
        return False

    async with chunk_renderer.render_semaphore:
        # Re-read under the permit: this is the set we are allowed to clear.
        dirty = await _fetch_dirty_chunks()
        stale = await _needs_full_rebuild()
        if not dirty and not stale:
            return False

        if dirty:
            images = [
                (cx, cy, await chunk_renderer.load_or_render_chunk_image(cx, cy))
                for cx, cy in dirty
            ]
            overview_data = await chunk_renderer.update_overview_chunks(images)
        else:
            # Stale with nothing dirty: chunks were rendered out of band (a
            # restore, or render_chunks.py --chunks-only) and no save will ever
            # arrive to fold them in. Rebuild from every chunk image.
            logger.info("Overview stale with no dirty chunks, full re-render")
            overview_data = await chunk_renderer.render_mosaic_overview()

        version = await storage.save_mosaic_overview(overview_data)

        if dirty:
            await db.execute(
                "UPDATE chunks SET dirty = FALSE WHERE chunk_id = ANY($1::text[])",
                [f"{cx}:{cy}" for cx, cy in dirty],
            )

    # Permit released before touching the network: manager.broadcast awaits every
    # connection in turn, and one backpressured client would otherwise pin the
    # permit and stall every render behind it.
    _schedule_background_task(
        manager.broadcast({"type": "overview_updated", "version": version})
    )

    logger.debug(f"Overview rebuilt to v{version} from {len(dirty)} dirty chunk(s)")
    return True


async def _run_loop() -> None:
    """Rebuild the overview at most once per coalesce window, while work exists."""
    while True:
        await _wake.wait()
        # Collect everything that lands during the window, then clear before the
        # rebuild so marks arriving mid-render re-arm us for the next pass.
        await asyncio.sleep(settings.overview_coalesce_seconds)
        _wake.clear()

        try:
            await flush_pending()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Dirty flags survive, so re-arm and retry on the next window rather
            # than waiting for someone to happen to draw again.
            logger.error(f"Overview rebuild failed: {e}")
            request_rebuild()


def start() -> None:
    """Start the coalescing loop (idempotent)."""
    global _loop_task
    if _loop_task is not None and not _loop_task.done():
        return
    _loop_task = asyncio.create_task(_run_loop())
    logger.info(
        f"Overview coalescer started " f"(window {settings.overview_coalesce_seconds}s)"
    )


async def stop() -> None:
    """Stop the coalescing loop."""
    global _loop_task
    task = _loop_task
    _loop_task = None
    if task is None or task.done():
        return
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("Overview coalescer stopped")


def _reset_state() -> None:
    """Clear module state. Used by tests between cases."""
    global _loop_task
    _loop_task = None
    _wake.clear()
    _background_tasks.clear()
