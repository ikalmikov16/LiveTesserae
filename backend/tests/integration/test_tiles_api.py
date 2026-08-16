"""Tests for tile CRUD HTTP endpoints."""

import asyncio

import pytest

from app.services.database import db
from tests.integration.conftest import drain_background_tasks


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


async def test_get_tile_cache_header_requires_revalidation(client, valid_pixel_data):
    """Tile URLs carry no version, so they must never be cached by age.

    This used to send a one-year max-age, survivable only because the client
    asked for no-store. Put a CDN in front of /api and every visitor would get
    pixels frozen for a year.
    """
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    r = await client.get("/api/tiles/5/5")
    assert "no-cache" in r.headers["cache-control"]
    assert "max-age=31536000" not in r.headers.get("cache-control", "")
    assert r.headers["etag"] == '"tile_5_5_v1"'


async def test_get_tile_etag_returns_304(client, valid_pixel_data):
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    etag = (await client.get("/api/tiles/5/5")).headers["etag"]

    r = await client.get("/api/tiles/5/5", headers={"If-None-Match": etag})
    assert r.status_code == 304
    assert r.content == b""


async def test_get_tile_etag_changes_when_pixels_change(
    client, valid_pixel_data, white_pixel_data
):
    """A stale validator is worse than none — it would pin the old pixels."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    first = (await client.get("/api/tiles/5/5")).headers["etag"]

    await client.put("/api/tiles/5/5", content=white_pixel_data)
    r = await client.get("/api/tiles/5/5", headers={"If-None-Match": first})

    assert r.status_code == 200, "an edited tile must not answer 304 to the old tag"
    assert r.content == white_pixel_data
    assert r.headers["etag"] != first


async def test_get_tile_accepts_weak_and_multiple_etags(client, valid_pixel_data):
    """CDNs weaken validators and browsers may send a list."""
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    etag = (await client.get("/api/tiles/5/5")).headers["etag"]

    r = await client.get(
        "/api/tiles/5/5", headers={"If-None-Match": f'"other", W/{etag}'}
    )
    assert r.status_code == 304


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


async def test_delete_route_is_not_exposed(client, valid_pixel_data):
    """
    There must be no public delete. The API is unauthenticated, so an open
    DELETE would let a single loop erase the mosaic. Resetting a tile is an
    operator action via the service layer.

    Asserts the property (the tile survives) rather than a specific status:
    the exact code for a method mismatch is Starlette's to choose, and
    requirements.txt pins only fastapi>=0.109.0.
    """
    await client.put("/api/tiles/5/5", content=valid_pixel_data)
    await drain_background_tasks()

    r = await client.delete("/api/tiles/5/5")
    assert r.status_code != 200, "DELETE must not be routable"
    assert r.status_code in (404, 405)

    # The tile is untouched.
    assert (await client.get("/api/tiles/5/5")).status_code == 200

    # Belt and braces: no DELETE handler is registered for the tile path.
    from app.main import app

    for route in app.routes:
        if getattr(route, "path", None) == "/api/tiles/{x}/{y}":
            assert "DELETE" not in getattr(route, "methods", set())


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
