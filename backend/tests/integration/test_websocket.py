"""Tests for WebSocket connections, subscriptions, and message delivery."""

import time

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.websocket.manager import manager


@pytest.fixture
def ws_app():
    """Starlette TestClient for sync WebSocket testing."""
    return TestClient(app)


def test_ws_connect(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        assert len(manager.active_connections) == 1


def test_ws_subscribe(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "chunks": ["0:0", "1:1"]})
        time.sleep(0.05)
        conns = list(manager.subscriptions.values())
        assert len(conns) == 1
        assert "0:0" in conns[0]
        assert "1:1" in conns[0]


def test_ws_subscribe_populates_reverse_index(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "chunks": ["0:0"]})
        time.sleep(0.05)
        assert len(manager.chunk_subscribers.get("0:0", set())) == 1


def test_ws_unsubscribe_stops_updates(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "chunks": ["0:0"]})
        time.sleep(0.05)
        ws.send_json({"type": "unsubscribe", "chunks": ["0:0"]})
        time.sleep(0.05)
        subs = manager.chunk_subscribers.get("0:0", set())
        assert len(subs) == 0


def test_ws_multiple_subscribers(ws_app):
    with ws_app.websocket_connect("/ws") as ws1:
        with ws_app.websocket_connect("/ws") as ws2:
            ws1.send_json({"type": "subscribe", "chunks": ["0:0"]})
            ws2.send_json({"type": "subscribe", "chunks": ["0:0"]})
            time.sleep(0.05)
            assert len(manager.chunk_subscribers.get("0:0", set())) == 2


def test_ws_invalid_json(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_text("this is not json {{{")
        time.sleep(0.05)
        # Connection still alive — can still subscribe
        ws.send_json({"type": "subscribe", "chunks": ["0:0"]})
        time.sleep(0.05)
        conns = list(manager.subscriptions.values())
        assert len(conns) == 1


def test_ws_unknown_message_type(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "nonexistent_type"})
        time.sleep(0.05)
        assert len(manager.active_connections) == 1


def test_ws_disconnect_cleanup(ws_app):
    with ws_app.websocket_connect("/ws"):
        assert len(manager.active_connections) == 1
    time.sleep(0.1)
    assert len(manager.active_connections) == 0


def test_ws_disconnect_cleans_subscriptions(ws_app):
    with ws_app.websocket_connect("/ws") as ws:
        ws.send_json({"type": "subscribe", "chunks": ["0:0", "1:1"]})
        time.sleep(0.05)
        assert len(manager.chunk_subscribers.get("0:0", set())) == 1
    time.sleep(0.1)
    # After disconnect, subscriber sets should be cleaned
    assert len(manager.chunk_subscribers.get("0:0", set())) == 0
    assert len(manager.chunk_subscribers.get("1:1", set())) == 0
