"""Tests for the shared get_client_ip utility."""

from unittest.mock import MagicMock

from app.utils import get_client_ip


def _make_conn(headers=None, client_host=None):
    conn = MagicMock()
    conn.headers = headers or {}
    if client_host:
        conn.client = MagicMock()
        conn.client.host = client_host
    else:
        conn.client = None
    return conn


def test_get_client_ip_from_forwarded_for():
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50"}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "203.0.113.50"


def test_get_client_ip_multiple_proxies():
    conn = _make_conn(
        headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1, 10.0.0.2"},
        client_host="10.0.0.2",
    )
    assert get_client_ip(conn) == "1.2.3.4"


def test_get_client_ip_no_header_falls_back():
    conn = _make_conn(client_host="192.168.1.100")
    assert get_client_ip(conn) == "192.168.1.100"


def test_get_client_ip_no_client():
    conn = _make_conn()
    assert get_client_ip(conn) == "unknown"
