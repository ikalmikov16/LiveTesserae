import json
import logging
from pathlib import Path

import aiofiles
import aiofiles.os

from app.config import settings

logger = logging.getLogger(__name__)

# Version tracking file name
CHUNK_VERSIONS_FILE = "chunk_versions.json"


def get_chunk_coords(x: int, y: int) -> tuple[int, int]:
    """Calculate chunk coordinates from tile coordinates."""
    return x // settings.chunk_size, y // settings.chunk_size


def get_tile_path(x: int, y: int) -> Path:
    """
    Get hierarchical path for a tile image.
    
    Structure: tiles/{cx}/{cy}/{x}_{y}.png
    Example: tiles/5/3/512_384.png for tile (512, 384) in chunk (5, 3)
    """
    cx, cy = get_chunk_coords(x, y)
    return Path(settings.tiles_path) / str(cx) / str(cy) / f"{x}_{y}.png"


async def ensure_tile_directory(x: int, y: int) -> Path:
    """Ensure the directory for a tile exists, create if needed."""
    tile_path = get_tile_path(x, y)
    directory = tile_path.parent
    
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Created directory: {directory}")
    
    return tile_path


async def save_tile_image(x: int, y: int, image_data: bytes) -> Path:
    """
    Save tile image to hierarchical filesystem.
    
    Returns the path where the image was saved.
    """
    tile_path = await ensure_tile_directory(x, y)
    
    async with aiofiles.open(tile_path, "wb") as f:
        await f.write(image_data)
    
    logger.debug(f"Saved tile image: {tile_path}")
    return tile_path


async def get_tile_image(x: int, y: int) -> bytes | None:
    """
    Read tile image from filesystem.
    
    Returns None if tile doesn't exist (default tile).
    """
    tile_path = get_tile_path(x, y)
    
    if not tile_path.exists():
        return None
    
    async with aiofiles.open(tile_path, "rb") as f:
        return await f.read()


async def delete_tile_image(x: int, y: int) -> bool:
    """
    Delete tile image from filesystem.
    
    Returns True if deleted, False if didn't exist.
    """
    tile_path = get_tile_path(x, y)
    
    if not tile_path.exists():
        return False
    
    await aiofiles.os.remove(tile_path)
    logger.debug(f"Deleted tile image: {tile_path}")
    
    # Clean up empty directories (optional, keeps filesystem tidy)
    try:
        tile_path.parent.rmdir()  # Only removes if empty
    except OSError:
        pass  # Directory not empty, that's fine
    
    return True


async def tile_exists(x: int, y: int) -> bool:
    """Check if a tile image exists on disk."""
    return get_tile_path(x, y).exists()


def ensure_storage_directories() -> None:
    """Ensure base storage directories exist on startup."""
    tiles_dir = Path(settings.tiles_path)
    chunks_dir = Path(settings.chunks_path)
    
    tiles_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Storage directories ready: {tiles_dir}, {chunks_dir}")


# =============================================================================
# Chunk Storage Functions (Level 0 & Level 1)
# =============================================================================


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


async def load_chunk_versions() -> dict:
    """Load version info from JSON file."""
    versions_path = get_chunk_versions_path()
    if not versions_path.exists():
        return {"chunks": {}, "overview": 0, "overview_stale": True}
    try:
        async with aiofiles.open(versions_path, "r") as f:
            content = await f.read()
            return json.loads(content)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"Failed to load chunk versions, using defaults: {e}")
        return {"chunks": {}, "overview": 0, "overview_stale": True}


async def save_chunk_versions(versions: dict) -> None:
    """Save version info to JSON file."""
    versions_path = get_chunk_versions_path()
    versions_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(versions_path, "w") as f:
        await f.write(json.dumps(versions, indent=2))


async def increment_chunk_version(cx: int, cy: int) -> int:
    """Increment chunk version and mark overview as stale."""
    versions = await load_chunk_versions()
    chunk_key = f"{cx}_{cy}"
    versions["chunks"][chunk_key] = versions["chunks"].get(chunk_key, 0) + 1
    versions["overview_stale"] = True
    await save_chunk_versions(versions)
    return versions["chunks"][chunk_key]


async def increment_overview_version() -> int:
    """Increment overview version and clear stale flag."""
    versions = await load_chunk_versions()
    versions["overview"] = versions.get("overview", 0) + 1
    versions["overview_stale"] = False
    await save_chunk_versions(versions)
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
