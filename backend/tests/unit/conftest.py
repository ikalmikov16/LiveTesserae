"""Unit test conftest — mocks and isolated storage fixtures."""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    """AsyncMock of Database with sensible defaults."""
    db = AsyncMock()
    db.fetchrow.return_value = None
    db.fetchval.return_value = None
    db.fetch.return_value = []
    db.execute.return_value = "OK"

    # Wire up transaction() as an async context manager
    conn = AsyncMock()
    conn.fetchrow.return_value = None
    conn.execute.return_value = "OK"
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=conn)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    db.transaction.return_value = tx_ctx

    db._transaction_conn = conn
    return db


def _build_mock_ws():
    """Build a mock WebSocket with realistic .headers and .client."""
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock()
    ws.headers = {}
    ws.client = MagicMock()
    ws.client.host = "127.0.0.1"
    return ws


@pytest.fixture
def mock_ws():
    """Mock WebSocket for ConnectionManager tests."""
    return _build_mock_ws()


def make_mock_ws():
    """Factory for creating multiple mock WebSockets."""
    return _build_mock_ws()


@pytest.fixture
def tmp_storage(tmp_path, monkeypatch):
    """Redirect all storage to tmp_path for file-based tests."""
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()

    monkeypatch.setattr("app.config.settings.chunks_path", str(chunks_dir))
    monkeypatch.setattr("app.config.settings.storage_mode", "local")

    # Reset the version lock to prevent cross-test deadlocks
    import app.services.storage as storage_mod

    storage_mod._version_lock = asyncio.Lock()

    return chunks_dir
