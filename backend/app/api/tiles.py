import base64
import logging

from fastapi import APIRouter, HTTPException, Path, Request, Response

from app.config import settings
from app.models.tile import TileDeleteResponse, TileResponse, TileSaveResponse
from app.services import tiles as tile_service
from app.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter()

# RGB pixel data size: 32×32 pixels × 3 bytes (RGB) = 3072 bytes
RGB_DATA_SIZE = 32 * 32 * 3


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
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Get tile as raw RGB bytes.

    Returns 3072 bytes of RGB data (32×32×3, row-major order).
    Returns 404 if tile is in default (white) state.
    """
    validate_coordinates(x, y)

    pixel_data = await tile_service.get_tile_pixel_data(x, y)

    if pixel_data is None:
        raise HTTPException(status_code=404, detail="Tile not found (is default)")

    return Response(
        content=pixel_data,
        media_type="application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000"},
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

    pixel_data = await request.body()

    if not pixel_data:
        raise HTTPException(status_code=400, detail="No pixel data provided")

    validate_pixel_data(pixel_data)

    result = await tile_service.save_tile(x, y, pixel_data)

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


@router.delete("/tiles/{x}/{y}", response_model=TileDeleteResponse)
async def delete_tile(
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Delete a tile (reset to default state).

    Removes the tile from the database.
    """
    validate_coordinates(x, y)

    tile_id = tile_service.calculate_tile_id(x, y)
    deleted = await tile_service.delete_tile(x, y)

    if not deleted:
        raise HTTPException(status_code=404, detail="Tile not found (already default)")

    return TileDeleteResponse(tile_id=tile_id)
