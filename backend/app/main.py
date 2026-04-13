import asyncio
import json as json_mod
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import mosaic, tiles, chunks
from app.config import settings
from app.services.database import db
from app.services.storage import ensure_storage_directories
from app.websocket import router as ws_router


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json_mod.dumps(
            {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
                **(
                    {"exc": self.formatException(record.exc_info)}
                    if record.exc_info
                    else {}
                ),
            }
        )


# Configure logging
_log_level = getattr(logging, settings.log_level.upper(), logging.INFO)
_handler = logging.StreamHandler()
if settings.log_format == "json":
    _handler.setFormatter(JSONFormatter())
else:
    _handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
_root = logging.getLogger()
_root.setLevel(_log_level)
_root.addHandler(_handler)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown."""
    # Startup
    logger.info("Starting Live Tesserae API...")

    # Ensure storage directories exist
    ensure_storage_directories()

    # Connect to database
    await db.connect()
    await db.init_schema()

    logger.info("Live Tesserae API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Live Tesserae API...")

    from app.services.tiles import _background_tasks

    if _background_tasks:
        logger.info(f"Draining {len(_background_tasks)} background tasks...")
        try:
            await asyncio.wait_for(
                asyncio.gather(*list(_background_tasks), return_exceptions=True),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Background task drain timed out after 10s, proceeding with shutdown"
            )

    await db.disconnect()
    logger.info("Live Tesserae API shutdown complete")


app = FastAPI(
    title="Live Tesserae",
    description="Collaborative mosaic API",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS - origins from environment variable (comma-separated)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(tiles.router, prefix="/api", tags=["tiles"])
app.include_router(mosaic.router, prefix="/api", tags=["mosaic"])
app.include_router(chunks.router, prefix="/api", tags=["chunks"])

# Register WebSocket router
app.include_router(ws_router, tags=["websocket"])


@app.get("/health")
async def health():
    """Health check endpoint — returns 503 when the database is unreachable
    so the ALB only routes traffic to fully-ready tasks."""
    db_status = "disconnected"

    try:
        if db.pool:
            result = await db.fetchval("SELECT 1")
            if result == 1:
                db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = "error"

    body = {
        "database": db_status,
        "mosaic": {
            "grid_size": f"{settings.grid_width}x{settings.grid_height}",
            "tile_size": settings.tile_size,
            "chunk_size": settings.chunk_size,
        },
    }

    if db_status != "connected":
        body["status"] = "unavailable"
        return JSONResponse(content=body, status_code=503)

    body["status"] = "ok"
    return body
