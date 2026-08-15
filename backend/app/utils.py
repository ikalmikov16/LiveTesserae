from fastapi import Request, WebSocket

from app.config import settings


def _forwarded_for(conn: Request | WebSocket) -> str | None:
    """
    Read X-Forwarded-For, joining repeated headers.

    A client can send the header more than once. Per RFC 7230 repeated headers
    are equivalent to one comma-joined header, but ``headers.get()`` returns
    only the first occurrence — which is the attacker-controlled one when a
    proxy appends to the last. Join every occurrence so positional indexing
    from the right stays correct.
    """
    getlist = getattr(conn.headers, "getlist", None)
    if getlist is not None:
        values = getlist("x-forwarded-for")
        return ", ".join(values) if values else None
    return conn.headers.get("x-forwarded-for")


def get_client_ip(conn: Request | WebSocket) -> str:
    """
    Extract the real client IP, trusting only proxies we control.

    X-Forwarded-For is client-controlled: a request can arrive with the header
    already populated with forged entries. Each trusted proxy *appends* the
    peer address it actually saw, so only the rightmost
    ``settings.trusted_proxy_hops`` entries are written by our own
    infrastructure. Indexing from the right is therefore the only safe read;
    taking the leftmost entry lets any client pick its own identity and bypass
    rate limiting and per-IP connection caps.

    With ``trusted_proxy_hops = 0`` (local dev, no proxy in front) the header is
    ignored entirely and the socket peer is used.
    """
    hops = settings.trusted_proxy_hops

    if hops > 0:
        forwarded = _forwarded_for(conn)
        if forwarded:
            parts = [p.strip() for p in forwarded.split(",")]
            parts = [p for p in parts if p]
            # Fewer entries than expected means the chain is not what we were
            # configured for; fall back to the socket peer rather than trust a
            # client-supplied entry.
            if len(parts) >= hops:
                return parts[-hops]

    if conn.client:
        return conn.client.host

    return "unknown"
