"""Tests for tile CRUD HTTP endpoints."""

import asyncio

import pytest

from app.services.database import db


async def test_put_tile_success(client, valid_pixel_data):
    r = await client.put("/api/tiles/5/5", content=valid_pixel_data)
    assert r.status_code == 200
    data = r.json()
    assert data["tile_id"] == "5:5"
    assert data["chunk_id"] == "0:0"
    assert data["version"] == 1


async def test_put_tile_overwrite(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.put("/api/tiles/5/5", content=valid_pixel_data)
    assert r.status_code == 200
    assert r.json()["version"] == 2


async def test_put_tile_empty_body(client):
    r = await client.put("/api/tiles/0/0", content=b"")
    assert r.status_code == 400
    assert "No pixel data" in r.json()["detail"]


async def test_put_tile_wrong_size(client):
    r = await client.put("/api/tiles/0/0", content=bytes(100))
    assert r.status_code == 400
    assert "3072 bytes" in r.json()["detail"]


async def test_put_tile_boundary_coords(client, valid_pixel_data):
    r1 = await client.put("/api/tiles/0/0", content=valid_pixel_data)
    assert r1.status_code == 200

    r2 = await client.put("/api/tiles/999/999", content=valid_pixel_data)
    assert r2.status_code == 200


async def test_put_tile_out_of_bounds(client, valid_pixel_data):
    r = await client.put("/api/tiles/1000/0", content=valid_pixel_data)
    assert r.status_code in (400, 422)


async def test_put_tile_with_session_id(client, valid_pixel_data):
    await client.put(
        "/api/tiles/5/5",
        content=valid_pixel_data,
        headers={"X-Session-Id": "test-session-123"},
    )
    count = await db.fetchval(
        "SELECT COUNT(*) FROM edit_log WHERE session_id = $1",
        "test-session-123",
    )
    assert count == 1


async def test_put_tile_without_session_id(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    count = await db.fetchval("SELECT COUNT(*) FROM edit_log")
    assert count == 0


async def test_get_tile_exists(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.get("/api/tiles/5/5")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert len(r.content) == 3072
    assert r.content == valid_pixel_data


async def test_get_tile_not_found(client):
    r = await client.get("/api/tiles/0/0")
    assert r.status_code == 404


async def test_get_tile_cache_header(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.get("/api/tiles/5/5")
    assert "max-age=31536000" in r.headers["cache-control"]


async def test_get_tile_info_exists(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.get("/api/tiles/5/5/info")
    assert r.status_code == 200
    data = r.json()
    assert data["tile_id"] == "5:5"
    assert data["chunk_id"] == "0:0"
    assert data["x"] == 5
    assert data["y"] == 5
    assert data["version"] == 1
    assert "updated_at" in data


async def test_get_tile_info_not_found(client):
    r = await client.get("/api/tiles/0/0/info")
    assert r.status_code == 404


async def test_delete_tile_exists(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.delete("/api/tiles/5/5")
    assert r.status_code == 200
    data = r.json()
    assert data["tile_id"] == "5:5"
    assert data["message"] == "Tile reset to default"


async def test_delete_tile_not_found(client):
    r = await client.delete("/api/tiles/0/0")
    assert r.status_code == 404


async def test_delete_then_get(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await client.delete("/api/tiles/5/5")
    r = await client.get("/api/tiles/5/5")
    assert r.status_code == 404


async def test_put_tile_correct_chunk_id(client, valid_pixel_data):
    r = await client.put("/api/tiles/512/384", content=valid_pixel_data)
    assert r.json()["chunk_id"] == "5:3"


async def test_concurrent_puts(client, valid_pixel_data):
    tasks = [
        client.put(f"/api/tiles/{i}/{i}", content=valid_pixel_data) for i in range(10)
    ]
    results = await asyncio.gather(*tasks)
    for r in results:
        assert r.status_code == 200


# ── production hardening: body size + rate limit ─────────────────────


async def test_put_tile_oversized_body_413(client):
    r = await client.put("/api/tiles/0/0", content=bytes(5000))
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


async def test_put_tile_oversized_content_length_413(client):
    r = await client.put(
        "/api/tiles/0/0",
        content=bytes(100),
        headers={"content-length": "9999"},
    )
    assert r.status_code == 413


async def test_put_tile_malformed_content_length_400(client):
    r = await client.put(
        "/api/tiles/0/0",
        content=bytes(100),
        headers={"content-length": "abc"},
    )
    assert r.status_code == 400
    assert "Content-Length" in r.json()["detail"]


async def test_put_tile_rate_limit_429(client, valid_pixel_data, monkeypatch):
    monkeypatch.setattr("app.config.settings.rate_limit_tile_save", 3)
    for i in range(3):
        r = await client.put(f"/api/tiles/{i}/0", content=valid_pixel_data)
        assert r.status_code == 200
    r = await client.put("/api/tiles/3/0", content=valid_pixel_data)
    assert r.status_code == 429
    assert "Rate limit" in r.json()["detail"]
