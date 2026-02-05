import asyncio
import io
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

# S3 session (lazy init)
_s3_session = None


def _get_s3_session():
    """Get or create aioboto3 session."""
    global _s3_session
    if _s3_session is None:
        import aioboto3

        _s3_session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
            region_name=settings.aws_region,
        )
    return _s3_session


def _is_s3_mode() -> bool:
    """Check if using S3 storage mode."""
    return settings.storage_mode == "s3"


def ensure_storage_directories() -> None:
    """Ensure base storage directories exist on startup (local mode only)."""
    if _is_s3_mode():
        logger.info(f"Using S3 storage: {settings.aws_s3_bucket}")
        return

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
    """Get local path for chunk preview image."""
    return Path(settings.chunks_path) / f"{cx}_{cy}.webp"


def get_mosaic_overview_path() -> Path:
    """Get local path for full mosaic overview image."""
    return Path(settings.chunks_path) / "mosaic_overview.webp"


def get_chunk_versions_path() -> Path:
    """Get local path for chunk versions JSON file."""
    return Path(settings.chunks_path) / CHUNK_VERSIONS_FILE


def _get_s3_chunk_key(cx: int, cy: int) -> str:
    """Get S3 key for chunk image."""
    return f"{cx}_{cy}.webp"


def _get_s3_overview_key() -> str:
    """Get S3 key for mosaic overview."""
    return "mosaic_overview.webp"


def _get_s3_versions_key() -> str:
    """Get S3 key for versions file."""
    return CHUNK_VERSIONS_FILE


# =============================================================================
# Chunk Image Operations
# =============================================================================


async def save_chunk_image(cx: int, cy: int, image_data: bytes) -> int:
    """
    Save rendered chunk preview and increment version.
    Returns the new version number.
    """
    if _is_s3_mode():
        return await _save_chunk_image_s3(cx, cy, image_data)
    else:
        return await _save_chunk_image_local(cx, cy, image_data)


async def _save_chunk_image_local(cx: int, cy: int, image_data: bytes) -> int:
    """Save chunk to local filesystem."""
    chunk_path = get_chunk_path(cx, cy)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(chunk_path, "wb") as f:
        await f.write(image_data)

    logger.debug(f"Saved chunk image: {chunk_path}")
    return await increment_chunk_version(cx, cy)


async def _save_chunk_image_s3(cx: int, cy: int, image_data: bytes) -> int:
    """Save chunk to S3."""
    key = _get_s3_chunk_key(cx, cy)
    session = _get_s3_session()

    async with session.client("s3") as s3:
        await s3.put_object(
            Bucket=settings.aws_s3_bucket,
            Key=key,
            Body=image_data,
            ContentType="image/webp",
        )

    logger.debug(f"Saved chunk image to S3: {key}")
    return await increment_chunk_version(cx, cy)


async def get_chunk_image(cx: int, cy: int) -> bytes | None:
    """Get chunk preview image if it exists."""
    if _is_s3_mode():
        return await _get_chunk_image_s3(cx, cy)
    else:
        return await _get_chunk_image_local(cx, cy)


async def _get_chunk_image_local(cx: int, cy: int) -> bytes | None:
    """Get chunk from local filesystem."""
    chunk_path = get_chunk_path(cx, cy)
    if not chunk_path.exists():
        return None
    async with aiofiles.open(chunk_path, "rb") as f:
        return await f.read()


async def _get_chunk_image_s3(cx: int, cy: int) -> bytes | None:
    """Get chunk from S3."""
    key = _get_s3_chunk_key(cx, cy)
    session = _get_s3_session()

    async with session.client("s3") as s3:
        try:
            response = await s3.get_object(
                Bucket=settings.aws_s3_bucket,
                Key=key,
            )
            async with response["Body"] as stream:
                return await stream.read()
        except s3.exceptions.NoSuchKey:
            return None
        except Exception as e:
            # Handle ClientError for NoSuchKey
            if "NoSuchKey" in str(e) or "404" in str(e):
                return None
            raise


# =============================================================================
# Mosaic Overview Operations
# =============================================================================


async def save_mosaic_overview(image_data: bytes) -> int:
    """Save mosaic overview and increment its version."""
    if _is_s3_mode():
        return await _save_mosaic_overview_s3(image_data)
    else:
        return await _save_mosaic_overview_local(image_data)


async def _save_mosaic_overview_local(image_data: bytes) -> int:
    """Save overview to local filesystem."""
    overview_path = get_mosaic_overview_path()
    overview_path.parent.mkdir(parents=True, exist_ok=True)

    async with aiofiles.open(overview_path, "wb") as f:
        await f.write(image_data)

    logger.debug(f"Saved mosaic overview: {overview_path}")
    return await increment_overview_version()


async def _save_mosaic_overview_s3(image_data: bytes) -> int:
    """Save overview to S3."""
    key = _get_s3_overview_key()
    session = _get_s3_session()

    async with session.client("s3") as s3:
        await s3.put_object(
            Bucket=settings.aws_s3_bucket,
            Key=key,
            Body=image_data,
            ContentType="image/webp",
        )

    logger.debug(f"Saved mosaic overview to S3: {key}")
    return await increment_overview_version()


async def get_mosaic_overview() -> bytes | None:
    """Get mosaic overview image if it exists."""
    if _is_s3_mode():
        return await _get_mosaic_overview_s3()
    else:
        return await _get_mosaic_overview_local()


async def _get_mosaic_overview_local() -> bytes | None:
    """Get overview from local filesystem."""
    overview_path = get_mosaic_overview_path()
    if not overview_path.exists():
        return None
    async with aiofiles.open(overview_path, "rb") as f:
        return await f.read()


async def _get_mosaic_overview_s3() -> bytes | None:
    """Get overview from S3."""
    key = _get_s3_overview_key()
    session = _get_s3_session()

    async with session.client("s3") as s3:
        try:
            response = await s3.get_object(
                Bucket=settings.aws_s3_bucket,
                Key=key,
            )
            async with response["Body"] as stream:
                return await stream.read()
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                return None
            raise


# =============================================================================
# Version Tracking
# =============================================================================


async def _load_chunk_versions_unsafe() -> dict:
    """Load version info (no locking - internal use only)."""
    if _is_s3_mode():
        return await _load_chunk_versions_s3()
    else:
        return await _load_chunk_versions_local()


async def _load_chunk_versions_local() -> dict:
    """Load versions from local filesystem."""
    versions_path = get_chunk_versions_path()
    if not versions_path.exists():
        return {"chunks": {}, "overview": 0, "overview_stale": True}
    try:
        async with aiofiles.open(versions_path, "r") as f:
            content = await f.read()
            return json.loads(content)
    except (json.JSONDecodeError, IOError):
        return {"chunks": {}, "overview": 0, "overview_stale": True}


async def _load_chunk_versions_s3() -> dict:
    """Load versions from S3."""
    key = _get_s3_versions_key()
    session = _get_s3_session()

    async with session.client("s3") as s3:
        try:
            response = await s3.get_object(
                Bucket=settings.aws_s3_bucket,
                Key=key,
            )
            async with response["Body"] as stream:
                content = await stream.read()
                return json.loads(content.decode("utf-8"))
        except Exception as e:
            if "NoSuchKey" in str(e) or "404" in str(e):
                return {"chunks": {}, "overview": 0, "overview_stale": True}
            raise


async def _save_chunk_versions_unsafe(versions: dict) -> None:
    """Save version info (no locking - internal use only)."""
    if _is_s3_mode():
        await _save_chunk_versions_s3(versions)
    else:
        await _save_chunk_versions_local(versions)


async def _save_chunk_versions_local(versions: dict) -> None:
    """Save versions to local filesystem."""
    versions_path = get_chunk_versions_path()
    versions_path.parent.mkdir(parents=True, exist_ok=True)
    # Write to temp file then rename for atomic operation
    temp_path = versions_path.with_suffix(".tmp")
    async with aiofiles.open(temp_path, "w") as f:
        await f.write(json.dumps(versions, indent=2))
    temp_path.rename(versions_path)


async def _save_chunk_versions_s3(versions: dict) -> None:
    """Save versions to S3."""
    key = _get_s3_versions_key()
    session = _get_s3_session()
    content = json.dumps(versions, indent=2)

    async with session.client("s3") as s3:
        await s3.put_object(
            Bucket=settings.aws_s3_bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="application/json",
        )


async def load_chunk_versions() -> dict:
    """Load version info from storage (thread-safe)."""
    async with _version_lock:
        return await _load_chunk_versions_unsafe()


async def save_chunk_versions(versions: dict) -> None:
    """Save version info to storage (thread-safe)."""
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
