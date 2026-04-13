from fastapi import Request, WebSocket


def get_client_ip(conn: Request | WebSocket) -> str:
    """
    Extract the real client IP, respecting X-Forwarded-For behind proxies.

    X-Forwarded-For format: "client, proxy1, proxy2"
    We take the first (leftmost) entry = original client.
    Falls back to direct connection IP for local development.
    """
    forwarded = conn.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    if conn.client:
        return conn.client.host

    return "unknown"
