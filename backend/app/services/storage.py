import asyncio
import json
import logging
from pathlib import Path

import aiofiles
import aiofiles.os

from app.config import settings

logger = logging.getLogger(__name__)

# Lock for version file access (prevents race conditions)
_version_lock = asyncio.Lock()

# Version tracking file name
CHUNK_VERSIONS_FILE = "chunk_versions.json"


def ensure_storage_directories() -> None:
    """Ensure base storage directories exist on startup."""
    # Only chunks directory needed (tile data stored in PostgreSQL)
    chunks_dir = Path(settings.chunks_path)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Storage directories ready: {chunks_dir}")


# =============================================================================
# Chunk Storage Functions (Level 0 & Level 1)
# =============================================================================


def get_chunk_coords(x: int, y: int) -> tuple[int, int]:
    """Calculate chunk coordinates from tile coordinates."""
    return x // settings.chunk_size, y // settings.chunk_size


def get_chunk_path(cx: int, cy: int) -> Path:
    """Get path for chunk preview image."""
    return Path(settings.chunks_path) / f"{cx}_{cy}.webp"


def get_mosaic_overview_path() -> Path:
    """Get path for full mosaic overview image."""
    return Path(settings.chunks_path) / "mosaic_overview.webp"


def get_chunk_versions_path() -> Path:
    """Get path for chunk versions JSON file."""
    return Path(settings.chunks_path) / CHUNK_VERSIONS_FILE


async def save_chunk_image(cx: int, cy: int, image_data: bytes) -> int:
    """
    Save rendered chunk preview and increment version.

    Returns the new version number.
    """
    chunk_path = get_chunk_path(cx, cy)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(chunk_path, "wb") as f:
        await f.write(image_data)

    logger.debug(f"Saved chunk image: {chunk_path}")

    # Increment and return version
    return await increment_chunk_version(cx, cy)


async def get_chunk_image(cx: int, cy: int) -> bytes | None:
    """Get chunk preview image if it exists."""
    chunk_path = get_chunk_path(cx, cy)
    if not chunk_path.exists():
        return None
    async with aiofiles.open(chunk_path, "rb") as f:
        return await f.read()


async def save_mosaic_overview(image_data: bytes) -> int:
    """Save mosaic overview and increment its version."""
    overview_path = get_mosaic_overview_path()
    overview_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(overview_path, "wb") as f:
        await f.write(image_data)

    logger.debug(f"Saved mosaic overview: {overview_path}")

    return await increment_overview_version()


async def get_mosaic_overview() -> bytes | None:
    """Get mosaic overview image if it exists."""
    overview_path = get_mosaic_overview_path()
    if not overview_path.exists():
        return None
    async with aiofiles.open(overview_path, "rb") as f:
        return await f.read()


# =============================================================================
# Version Tracking
# =============================================================================


async def _load_chunk_versions_unsafe() -> dict:
    """Load version info from JSON file (no locking - internal use only)."""
    versions_path = get_chunk_versions_path()
    if not versions_path.exists():
        return {"chunks": {}, "overview": 0, "overview_stale": True}
    try:
        async with aiofiles.open(versions_path, "r") as f:
            content = await f.read()
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {"chunks": {}, "overview": 0, "overview_stale": True}


async def _save_chunk_versions_unsafe(versions: dict) -> None:
    """Save version info to JSON file (no locking - internal use only)."""
    versions_path = get_chunk_versions_path()
    versions_path.parent.mkdir(parents=True, exist_ok=True)
    # Write to temp file then rename for atomic operation
    temp_path = versions_path.with_suffix(".tmp")
    async with aiofiles.open(temp_path, "w") as f:
        await f.write(json.dumps(versions, indent=2))
    temp_path.rename(versions_path)


async def load_chunk_versions() -> dict:
    """Load version info from JSON file (thread-safe)."""
    async with _version_lock:
        return await _load_chunk_versions_unsafe()


async def save_chunk_versions(versions: dict) -> None:
    """Save version info to JSON file (thread-safe)."""
    async with _version_lock:
        await _save_chunk_versions_unsafe(versions)


async def increment_chunk_version(cx: int, cy: int) -> int:
    """Increment chunk version and mark overview as stale."""
    async with _version_lock:
        versions = await _load_chunk_versions_unsafe()
        chunk_key = f"{cx}_{cy}"
        versions["chunks"][chunk_key] = versions["chunks"].get(chunk_key, 0) + 1
        versions["overview_stale"] = True
        await _save_chunk_versions_unsafe(versions)
        return versions["chunks"][chunk_key]


async def increment_overview_version() -> int:
    """Increment overview version and clear stale flag."""
    async with _version_lock:
        versions = await _load_chunk_versions_unsafe()
        versions["overview"] = versions.get("overview", 0) + 1
        versions["overview_stale"] = False
        await _save_chunk_versions_unsafe(versions)
        return versions["overview"]


async def get_chunk_version(cx: int, cy: int) -> int:
    """Get current version of a chunk."""
    versions = await load_chunk_versions()
    return versions["chunks"].get(f"{cx}_{cy}", 0)


async def get_overview_version() -> int:
    """Get current version of overview."""
    versions = await load_chunk_versions()
    return versions.get("overview", 0)


async def is_overview_stale() -> bool:
    """Check if overview needs re-rendering."""
    versions = await load_chunk_versions()
    return versions.get("overview_stale", True)
