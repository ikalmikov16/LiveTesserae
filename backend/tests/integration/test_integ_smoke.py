"""Smoke test — validates integration fixtures (DB connection, HTTP client)."""


async def test_db_connected():
    """Verify the test database is reachable."""
    from app.services.database import db

    result = await db.fetchval("SELECT 1")
    assert result == 1


async def test_client_works(client):
    """Verify the async HTTP client can reach the FastAPI app."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"
