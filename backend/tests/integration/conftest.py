"""Integration test conftest — real DB, real app, async HTTP client."""

import asyncio
import os

import httpx
import pytest

from app.config import settings
from app.services.database import db

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://tesserae:tesserae_local@localhost:5433/tesserae_test",
)


@pytest.fixture(scope="session", autouse=True)
async def setup_db(monkeypatch_session):
    """Connect to the TEST database, init schema, disconnect at end."""
    monkeypatch_session.setattr("app.config.settings.database_url", TEST_DATABASE_URL)
    db.pool = None
    await db.connect()
    await db.init_schema()
    yield
    await db.disconnect()


@pytest.fixture(scope="session")
def monkeypatch_session():
    """Session-scoped monkeypatch (built-in monkeypatch is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


@pytest.fixture(autouse=True)
async def clean_db():
    """Drain background tasks from prior test, then truncate all tables."""
    from app.services.tiles import _background_tasks

    if _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)
    await db.execute("TRUNCATE tiles, chunks, edit_log")


@pytest.fixture(autouse=True)
def clean_ws_manager():
    """Reset the global WebSocket manager between tests."""
    from app.websocket.manager import manager

    manager.active_connections.clear()
    manager.subscriptions.clear()
    manager.chunk_subscribers.clear()
    manager._pending_messages.clear()
    manager._batch_task = None


@pytest.fixture(autouse=True)
def clean_rate_limit():
    """Reset the rate limiter between tests."""
    from app.api.tiles import _rate_limit_store

    _rate_limit_store.clear()


@pytest.fixture(autouse=True)
def clean_stats_cache():
    """Reset the mosaic stats in-memory cache before each test."""
    from app.api.mosaic import _stats_cache

    _stats_cache["data"] = None
    _stats_cache["expires_at"] = 0.0


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    """Isolated storage directory per test — patches settings.chunks_path."""
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    monkeypatch.setattr("app.config.settings.chunks_path", str(chunks_dir))
    monkeypatch.setattr("app.config.settings.storage_mode", "local")

    import app.services.storage as storage_mod

    storage_mod._version_lock = asyncio.Lock()

    return chunks_dir


@pytest.fixture
async def client(storage_dir):
    """Async HTTP client bound to the FastAPI app via ASGI transport."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def drain_background_tasks():
    """Wait for all pending background tasks (chunk render, overview update) to complete."""
    from app.services.tiles import _background_tasks

    if _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)
