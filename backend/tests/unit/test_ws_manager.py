"""Tests for WebSocket ConnectionManager."""

import asyncio

import pytest
from unittest.mock import AsyncMock

from app.websocket.manager import ConnectionManager
from tests.unit.conftest import make_mock_ws


@pytest.fixture
def mgr():
    return ConnectionManager()


# ── connect / disconnect ────────────────────────────────────────────────


async def test_connect_adds_to_active(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    assert ws in mgr.active_connections
    assert len(mgr.active_connections) == 1


async def test_disconnect_removes_from_active(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.disconnect(ws)
    assert ws not in mgr.active_connections
    assert len(mgr.active_connections) == 0


# ── subscribe / unsubscribe ─────────────────────────────────────────────


async def test_subscribe_adds_to_forward_index(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0", "1:1"])
    assert mgr.subscriptions[ws] == {"0:0", "1:1"}


async def test_subscribe_adds_to_reverse_index(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])
    assert ws in mgr.chunk_subscribers["0:0"]


async def test_unsubscribe_removes_from_both_indexes(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0", "1:1"])
    mgr.unsubscribe(ws, ["0:0"])

    assert "0:0" not in mgr.subscriptions[ws]
    assert "1:1" in mgr.subscriptions[ws]
    assert ws not in mgr.chunk_subscribers.get("0:0", set())


async def test_unsubscribe_cleans_empty_sets(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])
    mgr.unsubscribe(ws, ["0:0"])
    assert "0:0" not in mgr.chunk_subscribers


async def test_disconnect_cleans_all_subscriptions(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0", "1:1", "2:2"])
    mgr.disconnect(ws)

    assert ws not in mgr.subscriptions
    assert "0:0" not in mgr.chunk_subscribers
    assert "1:1" not in mgr.chunk_subscribers
    assert "2:2" not in mgr.chunk_subscribers


# ── broadcast ───────────────────────────────────────────────────────────


async def test_broadcast_to_chunk_sends_to_subscribers(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])

    await mgr.broadcast_to_chunk("0:0", {"type": "test"})
    await mgr._flush_batch()

    ws.send_json.assert_called_once()


async def test_broadcast_to_chunk_skips_non_subscribers(mgr):
    ws1 = make_mock_ws()
    ws2 = make_mock_ws()
    await mgr.connect(ws1)
    await mgr.connect(ws2)
    mgr.subscribe(ws1, ["0:0"])
    mgr.subscribe(ws2, ["1:1"])

    await mgr.broadcast_to_chunk("0:0", {"type": "test"})
    await mgr._flush_batch()

    ws1.send_json.assert_called_once()
    ws2.send_json.assert_not_called()


async def test_broadcast_to_all(mgr):
    ws1 = make_mock_ws()
    ws2 = make_mock_ws()
    await mgr.connect(ws1)
    await mgr.connect(ws2)

    await mgr.broadcast({"type": "global"})

    ws1.send_json.assert_called_once_with({"type": "global"})
    ws2.send_json.assert_called_once_with({"type": "global"})


async def test_failed_send_disconnects_client(mgr):
    ws = make_mock_ws()
    ws.send_json.side_effect = Exception("connection closed")
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])

    await mgr.broadcast_to_chunk_immediate("0:0", {"type": "x"})

    assert ws not in mgr.active_connections


async def test_batch_single_message(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])

    msg = {"type": "tile_update", "x": 5, "y": 5}
    await mgr.broadcast_to_chunk("0:0", msg)
    await mgr._flush_batch()

    ws.send_json.assert_called_once_with(msg)


async def test_batch_multiple_messages(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, ["0:0"])

    msgs = [{"type": "tile_update", "x": i, "y": 0} for i in range(3)]
    for msg in msgs:
        await mgr.broadcast_to_chunk("0:0", msg)

    await mgr._flush_batch()

    ws.send_json.assert_called_once()
    call_arg = ws.send_json.call_args[0][0]
    assert call_arg["type"] == "tile_updates_batch"
    assert len(call_arg["updates"]) == 3


# ── connection limits ────────────────────────────────────────────────


async def test_connect_global_limit_rejects(mgr, monkeypatch):
    monkeypatch.setattr("app.config.settings.ws_max_connections", 2)
    ws1 = make_mock_ws()
    ws2 = make_mock_ws()
    ws3 = make_mock_ws()
    assert await mgr.connect(ws1) is True
    assert await mgr.connect(ws2) is True
    result = await mgr.connect(ws3)
    assert result is False
    ws3.close.assert_called_once()
    assert ws3.close.call_args[1]["code"] == 1013


async def test_connect_per_ip_limit_rejects(mgr, monkeypatch):
    monkeypatch.setattr("app.config.settings.ws_max_connections_per_ip", 2)
    ws1 = make_mock_ws()
    ws2 = make_mock_ws()
    ws3 = make_mock_ws()
    assert await mgr.connect(ws1) is True
    assert await mgr.connect(ws2) is True
    result = await mgr.connect(ws3)
    assert result is False
    ws3.close.assert_called_once()


async def test_connect_stores_client_ip(mgr):
    ws = make_mock_ws()
    await mgr.connect(ws)
    assert ws._client_ip == "127.0.0.1"


async def test_subscribe_caps_at_max(mgr, monkeypatch):
    monkeypatch.setattr("app.config.settings.ws_max_subscriptions", 5)
    ws = make_mock_ws()
    await mgr.connect(ws)
    mgr.subscribe(ws, [f"{i}:0" for i in range(8)])
    assert len(mgr.subscriptions[ws]) == 5

    mgr.subscribe(ws, ["0:1"])
    assert len(mgr.subscriptions[ws]) == 5
