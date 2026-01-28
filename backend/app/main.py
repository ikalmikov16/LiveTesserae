import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import mosaic, tiles, chunks
from app.config import settings
from app.services.database import db
from app.services.storage import ensure_storage_directories
from app.websocket import router as ws_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
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
    await db.disconnect()
    logger.info("Live Tesserae API shutdown complete")


app = FastAPI(
    title="Live Tesserae",
    description="Collaborative mosaic API",
    version="0.1.0",
    lifespan=lifespan,
)

# Configure CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite default port
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
    """Health check endpoint with database connectivity status."""
    db_status = "disconnected"
    
    try:
        if db.pool:
            # Test database connection
            result = await db.fetchval("SELECT 1")
            if result == 1:
                db_status = "connected"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        db_status = f"error: {str(e)}"
    
    return {
        "status": "ok",
        "database": db_status,
        "mosaic": {
            "grid_size": f"{settings.grid_width}x{settings.grid_height}",
            "tile_size": settings.tile_size,
            "chunk_size": settings.chunk_size,
        },
    }
