"""Tests for mosaic stats and info endpoints."""

import pytest


async def test_mosaic_info_shape(client):
    r = await client.get("/api/mosaic/info")
    assert r.status_code == 200
    data = r.json()
    for key in (
        "grid_width",
        "grid_height",
        "tile_size",
        "chunk_size",
        "total_tiles",
        "total_chunks",
        "edited_tiles",
    ):
        assert key in data


async def test_mosaic_info_derived_values(client):
    data = (await client.get("/api/mosaic/info")).json()
    assert data["total_tiles"] == 1_000_000
    assert data["total_chunks"] == 100


async def test_mosaic_info_edited_count(client, valid_pixel_data):
    for i in range(3):
        await client.put(f"/api/tiles/{i}/0", content=valid_pixel_data)
    data = (await client.get("/api/mosaic/info")).json()
    assert data["edited_tiles"] == 3


async def test_mosaic_stats_empty(client):
    data = (await client.get("/api/mosaic/stats")).json()
    assert data["edited_tiles"] == 0
    assert data["total_edits"] == 0
    assert data["unique_editors"] == 0
    assert data["pixels_painted"] == 0


async def test_mosaic_stats_after_edits(client, valid_pixel_data):
    for i in range(2):
        await client.put(
            f"/api/tiles/{i}/0",
            content=valid_pixel_data,
            headers={"X-Session-Id": "editor-a"},
        )
    data = (await client.get("/api/mosaic/stats")).json()
    assert data["edited_tiles"] == 2
    assert data["total_edits"] == 2
    assert data["pixels_painted"] == 2 * 1024


async def test_mosaic_stats_unique_editors(client, valid_pixel_data):
    await client.put(
        "/api/tiles/0/0",
        content=valid_pixel_data,
        headers={"X-Session-Id": "editor-a"},
    )
    await client.put(
        "/api/tiles/1/0",
        content=valid_pixel_data,
        headers={"X-Session-Id": "editor-b"},
    )
    data = (await client.get("/api/mosaic/stats")).json()
    assert data["unique_editors"] == 2


async def test_mosaic_stats_cache_returns_same(client, valid_pixel_data):
    data1 = (await client.get("/api/mosaic/stats")).json()
    assert data1["edited_tiles"] == 0

    await client.put("/api/tiles/0/0", content=valid_pixel_data)

    # Within 30s TTL — should return cached result
    data2 = (await client.get("/api/mosaic/stats")).json()
    assert data2["edited_tiles"] == 0  # still cached
