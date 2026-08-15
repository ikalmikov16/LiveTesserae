"""End-to-end lifecycle tests: save → DB → render → storage → broadcast."""

import io

from PIL import Image

from app.services import storage
from app.services import tiles as tile_service
from app.services.chunk_renderer import _get_tile_bounds_in_chunk
from app.services.database import db
from tests.integration.conftest import drain_background_tasks


async def test_full_save_pipeline(client, valid_pixel_data):
    r = await client.put("/api/tiles/5/5", content=valid_pixel_data)
    assert r.status_code == 200

    row = await db.fetchrow("SELECT * FROM tiles WHERE tile_id = $1", "5:5")
    assert row is not None

    await drain_background_tasks()

    chunk_img = await storage.get_chunk_image(0, 0)
    assert chunk_img is not None

    overview_img = await storage.get_mosaic_overview()
    assert overview_img is not None


async def test_delete_pipeline(client, valid_pixel_data):
    """Deleting via the service layer still clears the tile from the chunk image.

    There is no public DELETE route (see test_tiles_api), but operators reset
    tiles through the service, and that path must repaint the chunk.
    """
    await client.put("/api/tiles/0/0", content=valid_pixel_data)
    await drain_background_tasks()

    await tile_service.delete_tile(0, 0)
    await drain_background_tasks()

    chunk_img = await storage.get_chunk_image(0, 0)
    assert chunk_img is not None

    img = Image.open(io.BytesIO(chunk_img))
    px, py, _, _ = _get_tile_bounds_in_chunk(0, 0)
    pixel = img.getpixel((px + 1, py + 1))
    assert pixel == (255, 255, 255), f"Expected white after delete, got {pixel}"


async def test_save_updates_chunk_version(client, valid_pixel_data):
    v_before = await storage.get_chunk_version(0, 0)
    assert v_before == 0

    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    v_after = await storage.get_chunk_version(0, 0)
    assert v_after > 0


async def test_save_marks_overview_stale_then_updates(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    # Background task should have re-rendered overview and cleared stale flag
    stale = await storage.is_overview_stale()
    assert stale is False


async def test_multiple_tiles_same_chunk(client, valid_pixel_data):
    coords = [(0, 0), (1, 0), (0, 1)]
    for x, y in coords:
        await client.put(f"/api/tiles/{x}/{y}", content=valid_pixel_data)

    await drain_background_tasks()

    chunk_img = await storage.get_chunk_image(0, 0)
    assert chunk_img is not None

    img = Image.open(io.BytesIO(chunk_img))
    for x, y in coords:
        px, py, _, _ = _get_tile_bounds_in_chunk(x, y)
        pixel = img.getpixel((px + 1, py + 1))
        assert pixel[0] > 200, f"Tile ({x},{y}) not found in chunk, got {pixel}"


async def test_tiles_across_chunks(client, valid_pixel_data):
    # (0,0) → chunk 0:0, (500,500) → chunk 5:5
    await client.put("/api/tiles/0/0", content=valid_pixel_data)
    await client.put("/api/tiles/500/500", content=valid_pixel_data)
    await drain_background_tasks()

    chunk_00 = await storage.get_chunk_image(0, 0)
    chunk_55 = await storage.get_chunk_image(5, 5)
    assert chunk_00 is not None
    assert chunk_55 is not None
