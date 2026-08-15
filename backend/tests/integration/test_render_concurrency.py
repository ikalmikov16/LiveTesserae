"""Render-path concurrency guarantees.

These pin the behaviour that keeps a 1 GB container alive under load:

* an HTTP request never blocks on rendering an image that already exists,
* concurrent requests for a missing image produce exactly one render,
* an abandoned request does not cancel the render other clients are waiting on,
* the shared render permit is never acquired twice on one path (which would
  deadlock the process permanently).

Each was reachable before this suite existed: /chunks/overview re-rendered a
5000x5000 (~75 MB) image in-request whenever the overview was stale, which is
almost always true right after an edit.
"""

import asyncio
import time

import pytest

from app.api import chunks as chunks_api
from app.services import chunk_renderer, storage
from app.services import tiles as tile_service
from tests.integration.conftest import drain_background_tasks


@pytest.fixture
def slow_overview_render(monkeypatch):
    """Replace the overview render with a slow, counted stand-in."""
    calls = {"count": 0}
    real = chunk_renderer.render_mosaic_overview

    async def _counted():
        calls["count"] += 1
        await asyncio.sleep(0.75)
        return await real()

    monkeypatch.setattr(chunk_renderer, "render_mosaic_overview", _counted)
    return calls


# --- a request must not render an image that already exists -----------------


async def test_stale_overview_is_served_without_blocking(
    client, valid_pixel_data, slow_overview_render
):
    """A stale overview is served as-is; the refresh happens out of band."""
    await client.put("/api/tiles/0/0", content=valid_pixel_data)
    await drain_background_tasks()

    cached = await storage.get_mosaic_overview()
    assert cached is not None

    # Mark stale exactly the way a tile save does.
    await storage.increment_chunk_version(0, 0)
    assert await storage.is_overview_stale() is True

    started = time.perf_counter()
    r = await client.get("/api/chunks/overview")
    elapsed = time.perf_counter() - started

    assert r.status_code == 200
    assert r.content == cached, "should serve the cached bytes, not a fresh render"
    assert elapsed < 0.5, (
        f"request blocked {elapsed:.2f}s on a render it should have deferred "
        "(render stand-in sleeps 0.75s)"
    )

    await drain_background_tasks()


async def test_stale_overview_schedules_a_background_refresh(
    client, valid_pixel_data, slow_overview_render
):
    """Serving stale must still repair the overview, or it stays stale forever."""
    await client.put("/api/tiles/0/0", content=valid_pixel_data)
    await drain_background_tasks()

    await storage.increment_chunk_version(0, 0)
    slow_overview_render["count"] = 0

    await client.get("/api/chunks/overview")
    await drain_background_tasks()

    assert slow_overview_render["count"] == 1
    assert await storage.is_overview_stale() is False


async def test_refresh_skipped_while_a_render_is_already_running(
    client, valid_pixel_data, slow_overview_render
):
    """Don't queue a redundant full render behind the one already in flight."""
    await client.put("/api/tiles/0/0", content=valid_pixel_data)
    await drain_background_tasks()
    await storage.increment_chunk_version(0, 0)
    slow_overview_render["count"] = 0

    # Hold the permit the way a post-save background render does.
    async with chunk_renderer.render_semaphore:
        for _ in range(5):
            r = await client.get("/api/chunks/overview")
            assert r.status_code == 200

    assert slow_overview_render["count"] == 0, "should defer to the running render"

    await drain_background_tasks()


# --- concurrent requests for a MISSING image collapse to one render ---------


async def test_concurrent_cold_overview_requests_render_once(
    client, storage_dir, slow_overview_render
):
    """
    Five clients hitting a cold overview must not allocate five 75 MB buffers.

    This is the OOM path: before single-flighting, every concurrent request
    started its own full render.
    """
    assert await storage.get_mosaic_overview() is None

    results = await asyncio.gather(
        *[client.get("/api/chunks/overview") for _ in range(5)]
    )

    for r in results:
        assert r.status_code == 200
        assert len(r.content) > 0
    # All five got identical bytes because they shared one render.
    assert len({r.content for r in results}) == 1
    assert slow_overview_render["count"] == 1, (
        f"expected 1 render for 5 concurrent cold requests, "
        f"got {slow_overview_render['count']}"
    )

    await drain_background_tasks()


async def test_concurrent_cold_chunk_requests_render_once(client, storage_dir):
    """Same guarantee for a cold Level-1 chunk."""
    calls = {"count": 0}
    real = chunk_renderer.render_chunk

    async def _counted(cx, cy):
        calls["count"] += 1
        await asyncio.sleep(0.4)
        return await real(cx, cy)

    chunk_renderer.render_chunk = _counted
    try:
        results = await asyncio.gather(
            *[client.get("/api/chunks/3/4") for _ in range(5)]
        )
    finally:
        chunk_renderer.render_chunk = real

    for r in results:
        assert r.status_code == 200
    assert calls["count"] == 1, f"expected 1 render, got {calls['count']}"

    await drain_background_tasks()


# --- an abandoned request must not cancel the shared render ----------------


async def test_disconnecting_client_does_not_cancel_shared_render(
    client, storage_dir, slow_overview_render
):
    """
    Starlette cancels a handler when its client disconnects. Without shielding,
    that cancellation propagates into the shared render task and aborts it for
    every other waiter too.
    """
    assert await storage.get_mosaic_overview() is None

    first = asyncio.create_task(chunks_api._overview_single_flight())
    await asyncio.sleep(0.05)  # let the render start
    second = asyncio.create_task(chunks_api._overview_single_flight())
    await asyncio.sleep(0.05)

    first.cancel()  # "client A goes away"

    result = await second
    assert isinstance(result, bytes) and len(result) > 0
    assert slow_overview_render["count"] == 1
    # The render still landed in storage despite the cancellation.
    assert await storage.get_mosaic_overview() is not None


# --- the permit must never be acquired twice on one path -------------------


async def test_save_and_chunk_request_do_not_deadlock(client, valid_pixel_data):
    """
    Regression guard for nested acquisition of the render permit.

    asyncio.Semaphore is not reentrant, so if a render helper acquired the
    permit its caller already holds, this hangs forever with no timeout and no
    recovery. Bounded so a regression fails instead of hanging the suite.
    """

    async def _exercise():
        await client.put("/api/tiles/7/7", content=valid_pixel_data)
        await drain_background_tasks()
        r = await client.get("/api/chunks/0/0")
        assert r.status_code == 200

    await asyncio.wait_for(_exercise(), timeout=30)
    assert not chunk_renderer.render_semaphore.locked(), "permit was not released"
