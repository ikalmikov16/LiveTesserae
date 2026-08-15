"""Tests for the tile service layer with a real database."""

from datetime import datetime

from app.services import tiles as tile_service
from app.services.database import db

# storage_dir comes from tests/integration/conftest.py. This module used to
# define its own copy, which shadowed the shared one and skipped its teardown
# drain, leaking background renders into the real backend/storage/chunks/.


async def test_save_tile_creates_row(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    row = await db.fetchrow("SELECT * FROM tiles WHERE tile_id = $1", "5:5")
    assert row is not None
    assert row["tile_id"] == "5:5"


async def test_save_tile_creates_chunk_row(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    row = await db.fetchrow("SELECT * FROM chunks WHERE chunk_id = $1", "0:0")
    assert row is not None


async def test_save_tile_upsert(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    await tile_service.save_tile(5, 5, valid_pixel_data)
    version = await db.fetchval("SELECT version FROM tiles WHERE tile_id = $1", "5:5")
    assert version == 2


async def test_save_tile_edit_log(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data, session_id="sess-1")
    count = await db.fetchval(
        "SELECT COUNT(*) FROM edit_log WHERE session_id = $1", "sess-1"
    )
    assert count == 1


async def test_save_tile_no_edit_log(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    count = await db.fetchval("SELECT COUNT(*) FROM edit_log")
    assert count == 0


async def test_get_tile_metadata(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    meta = await tile_service.get_tile_metadata(5, 5)
    assert meta is not None
    assert meta["tile_id"] == "5:5"
    assert meta["chunk_id"] == "0:0"
    assert meta["version"] == 1
    assert isinstance(meta["updated_at"], datetime)


async def test_get_tile_metadata_missing(storage_dir):
    meta = await tile_service.get_tile_metadata(99, 99)
    assert meta is None


async def test_get_tile_pixel_data(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    data = await tile_service.get_tile_pixel_data(5, 5)
    assert data == valid_pixel_data


async def test_get_tile_pixel_data_missing(storage_dir):
    data = await tile_service.get_tile_pixel_data(99, 99)
    assert data is None


async def test_tile_exists_true(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    assert await tile_service.tile_exists(5, 5) is True


async def test_tile_exists_false(storage_dir):
    assert await tile_service.tile_exists(99, 99) is False


async def test_delete_tile_removes_row(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    await tile_service.delete_tile(5, 5)
    row = await db.fetchrow("SELECT * FROM tiles WHERE tile_id = $1", "5:5")
    assert row is None


async def test_delete_tile_returns_none_if_missing(storage_dir):
    result = await tile_service.delete_tile(99, 99)
    assert result is None


async def test_save_tile_transaction_atomicity(valid_pixel_data, storage_dir):
    await tile_service.save_tile(5, 5, valid_pixel_data)
    tile_row = await db.fetchrow("SELECT * FROM tiles WHERE tile_id = $1", "5:5")
    chunk_row = await db.fetchrow("SELECT * FROM chunks WHERE chunk_id = $1", "0:0")
    assert tile_row is not None
    assert chunk_row is not None
