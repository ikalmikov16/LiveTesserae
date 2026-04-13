"""Tests for local filesystem storage operations."""

import pytest

from app.services import storage
from app.services.storage import (
    ensure_storage_directories,
    get_chunk_path,
    get_mosaic_overview_path,
)


async def test_ensure_storage_directories(tmp_storage):
    ensure_storage_directories()
    assert tmp_storage.exists()


async def test_save_chunk_image_creates_file(tmp_storage):
    await storage.save_chunk_image(0, 0, b"fake-webp-data")
    assert get_chunk_path(0, 0).exists()


async def test_get_chunk_image_exists(tmp_storage):
    test_data = b"chunk-image-bytes-here"
    await storage.save_chunk_image(1, 1, test_data)
    result = await storage.get_chunk_image(1, 1)
    assert result == test_data


async def test_get_chunk_image_missing(tmp_storage):
    result = await storage.get_chunk_image(99, 99)
    assert result is None


async def test_save_mosaic_overview_creates_file(tmp_storage):
    await storage.save_mosaic_overview(b"overview-data")
    assert get_mosaic_overview_path().exists()


async def test_get_mosaic_overview_missing(tmp_storage):
    result = await storage.get_mosaic_overview()
    assert result is None


async def test_save_get_roundtrip(tmp_storage):
    chunk_data = b"roundtrip-chunk-test-data"
    await storage.save_chunk_image(3, 4, chunk_data)
    assert await storage.get_chunk_image(3, 4) == chunk_data

    overview_data = b"roundtrip-overview-test-data"
    await storage.save_mosaic_overview(overview_data)
    assert await storage.get_mosaic_overview() == overview_data
