"""The Level-0 overview is rebuilt out of band, not once per tile save.

Re-encoding the overview inside every save was the scaling ceiling: ~1.7 s per
edit, capping the whole site at ~0.5 saves/sec. These pin the replacement —
saves only render their chunk and mark it dirty; one coalesced pass folds the
window's worth of dirty chunks into a single overview render.
"""

import asyncio

import pytest

from app.services import chunk_renderer, overview, storage
from app.services import tiles as tile_service
from app.services.database import db
from tests.integration.conftest import drain_background_tasks


async def _drain_chunk_renders() -> None:
    """Wait out the per-save chunk renders WITHOUT flushing the overview."""
    for _ in range(10):
        pending = list(tile_service._background_tasks)
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture
def count_overview_renders(monkeypatch):
    """Count every path that produces a new overview image."""
    calls = {"incremental": 0, "full": 0}

    real_incremental = chunk_renderer.update_overview_chunks
    real_full = chunk_renderer.render_mosaic_overview

    async def _incremental(chunks):
        calls["incremental"] += 1
        return await real_incremental(chunks)

    async def _full():
        calls["full"] += 1
        return await real_full()

    monkeypatch.setattr(chunk_renderer, "update_overview_chunks", _incremental)
    monkeypatch.setattr(chunk_renderer, "render_mosaic_overview", _full)
    return calls


async def test_save_renders_the_chunk_but_not_the_overview(
    client, storage_dir, valid_pixel_data, count_overview_renders
):
    """The expensive half of the save is gone from the save path."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await _drain_chunk_renders()

    assert await storage.get_chunk_image(0, 0) is not None, "chunk should render"
    assert count_overview_renders["incremental"] == 0
    assert count_overview_renders["full"] == 0
    assert await storage.get_mosaic_overview() is None

    await drain_background_tasks()


async def test_save_marks_its_chunk_dirty(client, storage_dir, valid_pixel_data):
    """chunks.dirty is what drives the rebuild — it was previously always FALSE."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await _drain_chunk_renders()

    dirty = await db.fetchval("SELECT dirty FROM chunks WHERE chunk_id = $1", "0:0")
    assert dirty is True

    await drain_background_tasks()


async def test_many_saves_coalesce_into_one_overview_render(
    client, storage_dir, valid_pixel_data, count_overview_renders
):
    """Five edits across five chunks cost one overview render, not five."""
    # Establish an overview first: a cold store legitimately takes the full
    # re-render path, and the coalescing claim is about the steady state.
    await client.put("/api/tiles/900/900", content=valid_pixel_data)
    await drain_background_tasks()
    count_overview_renders["incremental"] = 0
    count_overview_renders["full"] = 0

    coords = [(0, 0), (100, 0), (200, 0), (300, 0), (400, 0)]
    for x, y in coords:
        await client.put(f"/api/tiles/{x}/{y}", content=valid_pixel_data)
    await _drain_chunk_renders()

    rebuilt = await overview.flush_pending()
    assert rebuilt is True
    assert count_overview_renders["incremental"] == 1, (
        "five dirty chunks should be pasted into one decode/encode, got "
        f"{count_overview_renders['incremental']} renders"
    )
    assert count_overview_renders["full"] == 0

    await drain_background_tasks()


async def test_flush_clears_dirty_flags(
    client, storage_dir, valid_pixel_data, count_overview_renders
):
    """Composited chunks are cleared, so an idle site does no work at all."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await _drain_chunk_renders()
    await overview.flush_pending()

    remaining = await db.fetchval("SELECT COUNT(*) FROM chunks WHERE dirty = TRUE")
    assert remaining == 0

    count_overview_renders["incremental"] = 0
    count_overview_renders["full"] = 0
    assert await overview.flush_pending() is False, "nothing pending, nothing to do"
    assert count_overview_renders["incremental"] == 0
    assert count_overview_renders["full"] == 0


async def test_flush_broadcasts_the_new_overview_version(
    client, storage_dir, valid_pixel_data, monkeypatch
):
    """Clients still learn about the rebuild, just once per window."""
    from app.websocket.manager import manager

    sent = []

    async def _capture(message):
        sent.append(message)

    monkeypatch.setattr(manager, "broadcast", _capture)

    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    overview_msgs = [m for m in sent if m["type"] == "overview_updated"]
    assert len(overview_msgs) == 1
    assert overview_msgs[0]["version"] == await storage.get_overview_version()


async def test_dirty_flag_survives_a_concurrent_save(
    client, storage_dir, valid_pixel_data
):
    """A save must not clear a dirty flag the coalescer has not acted on yet.

    The chunks upsert used to write dirty = FALSE on every save, which is why
    the partial index built for exactly this had never done anything.
    """
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await _drain_chunk_renders()
    assert await db.fetchval("SELECT dirty FROM chunks WHERE chunk_id = $1", "0:0")

    # Second save into the same chunk, before any flush.
    await client.put("/api/tiles/6/6", content=valid_pixel_data)

    dirty = await db.fetchval("SELECT dirty FROM chunks WHERE chunk_id = $1", "0:0")
    assert dirty is True, "a save cleared a pending overview rebuild"

    await drain_background_tasks()


async def test_stale_overview_with_no_dirty_chunks_gets_a_full_rebuild(
    client, storage_dir, valid_pixel_data, count_overview_renders
):
    """Chunks rendered out of band still reach Level 0 with no save to trigger it."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    # Exactly what render_chunks.py --chunks-only leaves behind: chunk versions
    # bumped, overview marked stale, no dirty rows.
    await storage.increment_chunk_version(0, 0)
    assert await db.fetchval("SELECT COUNT(*) FROM chunks WHERE dirty = TRUE") == 0
    count_overview_renders["full"] = 0

    assert await overview.flush_pending() is True
    assert count_overview_renders["full"] == 1
    assert await storage.is_overview_stale() is False


async def test_virgin_store_does_not_render_a_blank_overview(storage_dir):
    """Nothing rendered yet means nothing to composite — don't burn a render."""
    assert await overview.flush_pending() is False
    assert await storage.get_mosaic_overview() is None


async def test_flush_does_not_hold_the_permit_while_broadcasting(
    client, storage_dir, valid_pixel_data, monkeypatch
):
    """broadcast awaits every connection; holding the permit through it would
    let one stalled client block every render in the process."""
    from app.websocket.manager import manager

    held = []

    async def _check(message):
        held.append(chunk_renderer.render_semaphore.locked())

    monkeypatch.setattr(manager, "broadcast", _check)

    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    assert held, "expected an overview broadcast"
    assert not any(held), "render permit was held during a WebSocket broadcast"
