"""A cold image store must never erase art that is still in the database.

The verified failure: 6 drawn tiles in Postgres, an empty image store (exactly
what a fresh deploy against a restored database looks like), one unrelated edit
— and all 6 tiles vanished from Levels 0 and 1. `update_chunk_tile` composited
onto a fresh white image, so the single tile being saved was all that survived,
and the loss was permanent because a chunk is only rebuilt when its image is
*missing* and a wrong one now existed.
"""

import io

from PIL import Image

from app.services import storage
from app.services import tiles as tile_service
from app.services.chunk_renderer import (
    _get_chunk_bounds_in_overview,
    _get_tile_bounds_in_chunk,
)
from tests.conftest import BLUE_TILE, RED_TILE
from tests.integration.conftest import drain_background_tasks

# Tiles seeded across chunk 0:0, standing in for a restored database.
SEEDED = [(0, 0), (1, 0), (2, 0), (0, 1), (1, 1), (2, 1)]


def _wipe_image_store(storage_dir) -> None:
    """Delete every rendered image and the version file — a virgin deploy."""
    for path in storage_dir.iterdir():
        path.unlink()


async def _seed_tiles(pixel_data: bytes) -> None:
    for x, y in SEEDED:
        await tile_service.save_tile(x, y, pixel_data)
    await drain_background_tasks()


async def test_edit_on_cold_store_keeps_existing_tiles_in_chunk(client, storage_dir):
    """One unrelated edit must not blank the other tiles out of the chunk image."""
    await _seed_tiles(RED_TILE)
    _wipe_image_store(storage_dir)
    assert await storage.get_chunk_image(0, 0) is None

    # An unrelated tile in the same chunk.
    r = await client.put("/api/tiles/50/50", content=BLUE_TILE)
    assert r.status_code == 200
    await drain_background_tasks()

    chunk_img = await storage.get_chunk_image(0, 0)
    assert chunk_img is not None
    img = Image.open(io.BytesIO(chunk_img))

    for x, y in SEEDED:
        px, py, _, _ = _get_tile_bounds_in_chunk(x, y)
        pixel = img.getpixel((px + 1, py + 1))
        assert pixel[0] > 200, (
            f"Tile ({x},{y}) was erased by an unrelated edit on a cold store, "
            f"got {pixel}"
        )

    # The edit itself landed too.
    px, py, _, _ = _get_tile_bounds_in_chunk(50, 50)
    assert img.getpixel((px + 1, py + 1))[2] > 200


def _chunk_is_blank(overview_bytes: bytes, cx: int, cy: int) -> bool:
    img = Image.open(io.BytesIO(overview_bytes))
    px, py, cw, ch = _get_chunk_bounds_in_overview(cx, cy)
    region = img.crop((px, py, px + cw, py + ch)).convert("RGB")
    # getextrema() is per band; a region with any ink has a min below white.
    return region.getextrema()[0][0] >= 250


async def test_missing_overview_is_rebuilt_from_chunks_not_white(client, storage_dir):
    """Level 0 has the same failure mode as Level 1.

    Overview gone, chunk images intact — exactly what losing the one overview
    object looks like. Pasting the edited chunk onto fresh white would erase
    every other chunk from the mosaic.
    """
    await tile_service.save_tile(0, 0, RED_TILE)
    await tile_service.save_tile(500, 500, RED_TILE)
    await drain_background_tasks()

    (storage_dir / "mosaic_overview.webp").unlink()
    assert await storage.get_mosaic_overview() is None

    # Edit chunk 0:0 only. Chunk 5:5 must survive in the rebuilt overview.
    await client.put("/api/tiles/1/1", content=BLUE_TILE)
    await drain_background_tasks()

    overview_img = await storage.get_mosaic_overview()
    assert overview_img is not None
    assert not _chunk_is_blank(overview_img, 5, 5), (
        "Chunk 5:5 is blank in the overview — a missing overview was composited "
        "onto white instead of rebuilt from the chunk images"
    )
    assert not _chunk_is_blank(overview_img, 0, 0)


async def test_total_wipe_recovers_rather_than_erasing_permanently(client, storage_dir):
    """A full wipe leaves chunks unrendered, but nothing is lost for good.

    The overview composites *chunk images*, so a chunk whose image is gone is
    absent from Level 0 until something rebuilds it — which is why a restore
    still has to run scripts/render_chunks.py before opening traffic. What must
    never happen is the old behaviour: a wrong image saved over it, after which
    the chunk is never rebuilt because an image now exists.
    """
    await tile_service.save_tile(0, 0, RED_TILE)
    await tile_service.save_tile(500, 500, RED_TILE)
    await drain_background_tasks()

    _wipe_image_store(storage_dir)

    await client.put("/api/tiles/1/1", content=BLUE_TILE)
    await drain_background_tasks()

    # Untouched chunk 5:5 has no image yet, so Level 0 cannot show it.
    assert _chunk_is_blank(await storage.get_mosaic_overview(), 5, 5)

    # But its art is intact: the first request re-renders it from the database…
    r = await client.get("/api/chunks/5/5")
    assert r.status_code == 200
    await drain_background_tasks()

    # …and that feeds straight back into Level 0.
    assert not _chunk_is_blank(await storage.get_mosaic_overview(), 5, 5), (
        "a re-rendered chunk never reached the overview — Level 0 would stay "
        "blank until someone happened to edit that chunk"
    )


async def test_cold_chunk_render_is_persisted(client, storage_dir):
    """The rebuilt chunk is saved, so the next edit starts from it, not white."""
    await _seed_tiles(RED_TILE)
    _wipe_image_store(storage_dir)

    await client.put("/api/tiles/50/50", content=BLUE_TILE)
    await drain_background_tasks()

    # Second edit: the chunk image now exists, so this is the incremental path.
    await client.put("/api/tiles/60/60", content=BLUE_TILE)
    await drain_background_tasks()

    chunk_img = await storage.get_chunk_image(0, 0)
    img = Image.open(io.BytesIO(chunk_img))
    for x, y in SEEDED:
        px, py, _, _ = _get_tile_bounds_in_chunk(x, y)
        assert img.getpixel((px + 1, py + 1))[0] > 200, f"Tile ({x},{y}) lost"
