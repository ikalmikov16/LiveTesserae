"""Tests for the shared get_client_ip utility.

X-Forwarded-For is client-controlled. Trusted proxies *append* the peer they
saw, so the real client is the Nth entry from the right where N is the number
of proxies we run. These tests pin that indexing and the spoofing cases it is
there to defeat.
"""

from unittest.mock import MagicMock

import pytest

from app.utils import get_client_ip


def _make_conn(headers=None, client_host=None, repeated=None):
    conn = MagicMock()
    if repeated is not None:
        # Simulate Starlette Headers: repeated header values via getlist().
        conn.headers = MagicMock()
        conn.headers.getlist = MagicMock(return_value=repeated)
    else:
        # Plain dict has no getlist(), exercising the fallback path.
        conn.headers = headers or {}
    if client_host:
        conn.client = MagicMock()
        conn.client.host = client_host
    else:
        conn.client = None
    return conn


@pytest.fixture
def hops(monkeypatch):
    """Set trusted_proxy_hops for a test."""

    def _set(n):
        monkeypatch.setattr("app.config.settings.trusted_proxy_hops", n)

    return _set


# --- No proxy configured (default, local dev) -------------------------------


def test_ignores_forwarded_header_when_no_proxy_configured(hops):
    """Default hops=0: the header is untrusted input and must be ignored."""
    hops(0)
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50"}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "10.0.0.1"


def test_no_header_falls_back_to_socket(hops):
    hops(0)
    conn = _make_conn(client_host="192.168.1.100")
    assert get_client_ip(conn) == "192.168.1.100"


def test_no_client_returns_unknown(hops):
    hops(0)
    conn = _make_conn()
    assert get_client_ip(conn) == "unknown"


# --- One trusted proxy (ALB) ------------------------------------------------


def test_single_proxy_uses_rightmost_entry(hops):
    """ALB appends the peer it saw, so the real client is last."""
    hops(1)
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50"}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "203.0.113.50"


def test_single_proxy_ignores_forged_prefix(hops):
    """The spoofing case: forged entries on the left must not be selected."""
    hops(1)
    conn = _make_conn(
        headers={"x-forwarded-for": "1.1.1.1, 2.2.2.2, 203.0.113.50"},
        client_host="10.0.0.1",
    )
    assert get_client_ip(conn) == "203.0.113.50"


# --- Two trusted proxies (CloudFront -> ALB) --------------------------------


def test_two_proxies_uses_second_from_right(hops):
    hops(2)
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50, 70.132.0.1"},
        client_host="10.0.0.1",
    )
    assert get_client_ip(conn) == "203.0.113.50"


def test_two_proxies_ignores_forged_prefix(hops):
    hops(2)
    conn = _make_conn(
        headers={"x-forwarded-for": "9.9.9.9, 203.0.113.50, 70.132.0.1"},
        client_host="10.0.0.1",
    )
    assert get_client_ip(conn) == "203.0.113.50"


# --- Malformed / hostile input ---------------------------------------------


def test_too_few_entries_falls_back_to_socket(hops):
    """Chain shorter than configured: trust the socket, never a client entry."""
    hops(2)
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50"}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "10.0.0.1"


def test_empty_header_falls_back_to_socket(hops):
    hops(1)
    conn = _make_conn(headers={"x-forwarded-for": ""}, client_host="10.0.0.1")
    assert get_client_ip(conn) == "10.0.0.1"


def test_blank_entries_are_discarded(hops):
    """Trailing comma must not shift indexing onto an empty entry."""
    hops(1)
    conn = _make_conn(
        headers={"x-forwarded-for": "203.0.113.50, "}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "203.0.113.50"


def test_whitespace_is_stripped(hops):
    hops(1)
    conn = _make_conn(
        headers={"x-forwarded-for": "  203.0.113.50  "}, client_host="10.0.0.1"
    )
    assert get_client_ip(conn) == "203.0.113.50"


def test_repeated_headers_are_joined(hops):
    """
    A client sending its own X-Forwarded-For must not shadow the proxy's.

    headers.get() would return only the first (forged) header; joining every
    occurrence keeps right-indexing anchored to what the proxy appended.
    """
    hops(1)
    conn = _make_conn(repeated=["1.1.1.1", "203.0.113.50"], client_host="10.0.0.1")
    assert get_client_ip(conn) == "203.0.113.50"
