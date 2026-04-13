"""Tests for the health check endpoint."""


async def test_health_ok(client):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


async def test_health_mosaic_info(client):
    response = await client.get("/health")
    data = response.json()
    assert data["mosaic"]["grid_size"] == "1000x1000"
    assert data["mosaic"]["tile_size"] == 32
    assert data["mosaic"]["chunk_size"] == 100
