import base64
import logging
import time

from fastapi import APIRouter, HTTPException, Path, Request, Response

from app.config import settings
from app.models.tile import TileResponse, TileSaveResponse
from app.services import tiles as tile_service
from app.utils import get_client_ip
from app.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter()

# RGB pixel data size: 32×32 pixels × 3 bytes (RGB) = 3072 bytes
RGB_DATA_SIZE = 32 * 32 * 3

# In-memory rate limit store: IP -> list of request timestamps
_rate_limit_store: dict[str, list[float]] = {}

# The store gains an entry per distinct client IP and would otherwise grow for
# the lifetime of the process. Sweeping every N checks keeps it proportional to
# recent traffic without paying a full scan on every request.
_SWEEP_EVERY = 1000
_checks_since_sweep = 0


def _sweep_rate_limit_store(now: float, window: float) -> None:
    """Drop IPs whose most recent request has fallen out of the window."""
    stale = [
        ip
        for ip, timestamps in _rate_limit_store.items()
        if not timestamps or now - timestamps[-1] >= window
    ]
    for ip in stale:
        del _rate_limit_store[ip]


def _check_rate_limit(request: Request) -> None:
    """Enforce per-IP rate limiting on tile saves."""
    if settings.rate_limit_tile_save <= 0:
        return

    client_ip = get_client_ip(request)
    now = time.monotonic()
    window = settings.rate_limit_window_seconds

    global _checks_since_sweep
    _checks_since_sweep += 1
    if _checks_since_sweep >= _SWEEP_EVERY:
        _checks_since_sweep = 0
        _sweep_rate_limit_store(now, window)

    timestamps = _rate_limit_store.get(client_ip, [])
    timestamps = [t for t in timestamps if now - t < window]

    if len(timestamps) >= settings.rate_limit_tile_save:
        _rate_limit_store[client_ip] = timestamps
        raise HTTPException(429, "Rate limit exceeded. Try again shortly.")

    timestamps.append(now)
    _rate_limit_store[client_ip] = timestamps


def validate_coordinates(x: int, y: int) -> None:
    """Validate tile coordinates are within grid bounds."""
    if not (0 <= x < settings.grid_width):
        raise HTTPException(
            status_code=400,
            detail=f"x coordinate must be between 0 and {settings.grid_width - 1}",
        )
    if not (0 <= y < settings.grid_height):
        raise HTTPException(
            status_code=400,
            detail=f"y coordinate must be between 0 and {settings.grid_height - 1}",
        )


def validate_pixel_data(data: bytes) -> None:
    """
    Validate that data is valid RGB pixel data.

    Expected: 3072 bytes (32×32×3 RGB, row-major order)
    """
    if len(data) != RGB_DATA_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Pixel data must be exactly {RGB_DATA_SIZE} bytes (32×32×3 RGB). "
            f"Got {len(data)} bytes.",
        )


@router.get(
    "/tiles/{x}/{y}",
    response_class=Response,
    responses={
        200: {
            "content": {"application/octet-stream": {}},
            "description": "RGB pixel data (3072 bytes)",
        },
        404: {"description": "Tile not found (is default)"},
    },
)
async def get_tile(
    request: Request,
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Get tile as raw RGB bytes.

    Returns 3072 bytes of RGB data (32×32×3, row-major order).
    Returns 404 if tile is in default (white) state.

    Cached by validator, not by age. A tile URL has no version in it and its
    contents change whenever anyone paints, so the old one-year `max-age` was
    only survivable because the client asked for `no-store` and threw the
    caching away. Put a CDN in front of `/api` with that combination and every
    visitor gets pixels frozen for a year. `no-cache` still allows the browser
    and the CDN to store the body — it just requires a revalidation first, which
    the ETag turns into a cheap 304.
    """
    validate_coordinates(x, y)

    result = await tile_service.get_tile_pixel_data_with_version(x, y)

    if result is None:
        raise HTTPException(status_code=404, detail="Tile not found (is default)")

    pixel_data, version = result
    etag = f'"tile_{x}_{y}_v{version}"'
    headers = {"Cache-Control": "no-cache, must-revalidate", "ETag": etag}

    # If-None-Match may carry a list, and a CDN may weaken the tag.
    if_none_match = request.headers.get("if-none-match", "")
    if any(
        candidate.strip().removeprefix("W/") == etag
        for candidate in if_none_match.split(",")
        if candidate.strip()
    ):
        return Response(status_code=304, headers=headers)

    return Response(
        content=pixel_data,
        media_type="application/octet-stream",
        headers=headers,
    )


@router.get("/tiles/{x}/{y}/info", response_model=TileResponse)
async def get_tile_info(
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Get tile metadata (JSON).

    Returns tile information including version and last update time.
    """
    validate_coordinates(x, y)

    metadata = await tile_service.get_tile_metadata(x, y)

    if metadata is None:
        raise HTTPException(status_code=404, detail="Tile not found (is default)")

    return TileResponse(**metadata)


@router.put("/tiles/{x}/{y}", response_model=TileSaveResponse)
async def save_tile(
    request: Request,
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Save or update a tile.

    Accepts raw RGB bytes (3072 bytes = 32×32×3, row-major order).
    """
    validate_coordinates(x, y)
    _check_rate_limit(request)

    # Streaming body read with size limit
    MAX_BODY_SIZE = 4096
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_BODY_SIZE:
                raise HTTPException(413, "Request body too large")
        except ValueError:
            raise HTTPException(400, "Invalid Content-Length header")

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_SIZE:
            raise HTTPException(413, "Request body too large")
    pixel_data = bytes(body)

    if not pixel_data:
        raise HTTPException(status_code=400, detail="No pixel data provided")

    validate_pixel_data(pixel_data)

    session_id = request.headers.get("X-Session-Id")
    result = await tile_service.save_tile(x, y, pixel_data, session_id=session_id)

    # Broadcast update to WebSocket subscribers
    chunk_id = tile_service.calculate_chunk_id(x, y)
    await manager.broadcast_to_chunk(
        chunk_id,
        {
            "type": "tile_update",
            "x": x,
            "y": y,
            "pixels": base64.b64encode(pixel_data).decode("ascii"),
        },
    )

    return TileSaveResponse(
        tile_id=result["tile_id"],
        chunk_id=result["chunk_id"],
        version=result["version"],
    )


# NOTE: there is deliberately no public DELETE route. The API is unauthenticated
# by design (anyone may paint), but an open delete lets a single loop erase the
# mosaic. Resetting a tile is an operator action — use
# app.services.tiles.delete_tile from a script.
