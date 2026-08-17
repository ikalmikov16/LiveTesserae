"""Tests for chunk image and version endpoints."""

import io

from PIL import Image

from app.services import storage
from app.services.chunk_renderer import CHUNK_PREVIEW_SIZE


async def test_get_chunk_returns_webp(client):
    r = await client.get("/api/chunks/0/0")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"


async def test_get_chunk_empty(client):
    r = await client.get("/api/chunks/0/0")
    assert r.status_code == 200
    img = Image.open(io.BytesIO(r.content))
    assert img.size == (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE)


async def test_get_chunk_has_etag(client):
    r = await client.get("/api/chunks/0/0")
    assert "etag" in r.headers
    assert "0_0_v" in r.headers["etag"]


async def test_get_chunk_out_of_bounds(client):
    r = await client.get("/api/chunks/100/0")
    assert r.status_code == 400


async def test_get_chunk_version(client):
    r = await client.get("/api/chunks/0/0/version")
    assert r.status_code == 200
    data = r.json()
    assert data["cx"] == 0
    assert data["cy"] == 0
    assert isinstance(data["version"], int)


async def test_get_overview_returns_webp(client):
    r = await client.get("/api/chunks/overview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/webp"


async def test_get_overview_has_etag(client):
    r = await client.get("/api/chunks/overview")
    assert "etag" in r.headers
    assert "overview_v" in r.headers["etag"]


async def test_get_overview_version(client):
    r = await client.get("/api/chunks/overview/version")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["version"], int)
    assert isinstance(data["stale"], bool)


async def test_overview_stale_after_chunk_update(client):
    await storage.increment_chunk_version(0, 0)
    r = await client.get("/api/chunks/overview/version")
    assert r.json()["stale"] is True
