import base64
import io
import logging

from fastapi import APIRouter, HTTPException, Path, Request, Response
from PIL import Image

from app.config import settings
from app.models.tile import TileDeleteResponse, TileResponse, TileSaveResponse
from app.services import tiles as tile_service
from app.websocket import manager

logger = logging.getLogger(__name__)

router = APIRouter()

# PNG magic bytes
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


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


def validate_png_image(data: bytes) -> None:
    """
    Validate that data is a valid PNG image with correct dimensions.
    
    Raises HTTPException if invalid.
    """
    # Check minimum size
    if len(data) < 8:
        raise HTTPException(status_code=400, detail="Image data too small")
    
    # Check PNG magic bytes
    if not data.startswith(PNG_MAGIC):
        raise HTTPException(
            status_code=400,
            detail="Invalid image format. Must be PNG.",
        )
    
    # Check file size (reasonable limit for 32x32 PNG)
    max_size = 50 * 1024  # 50KB should be more than enough
    if len(data) > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large. Maximum size is {max_size // 1024}KB.",
        )
    
    # Validate dimensions using Pillow
    try:
        img = Image.open(io.BytesIO(data))
        width, height = img.size
        
        if width != settings.tile_size or height != settings.tile_size:
            raise HTTPException(
                status_code=400,
                detail=f"Image must be exactly {settings.tile_size}x{settings.tile_size} pixels. "
                       f"Got {width}x{height}.",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid PNG image: {str(e)}",
        )


@router.get(
    "/tiles/{x}/{y}",
    response_class=Response,
    responses={
        200: {"content": {"image/png": {}}, "description": "Tile image"},
        404: {"description": "Tile not found (is default)"},
    },
)
async def get_tile(
    x: int = Path(ge=0, lt=settings.grid_width, description="X coordinate"),
    y: int = Path(ge=0, lt=settings.grid_height, description="Y coordinate"),
):
    """
    Get a tile image.
    
    Returns the PNG image data, or 404 if the tile is in default state.
    """
    validate_coordinates(x, y)
    
    image_data = await tile_service.get_tile_image(x, y)
    
    if image_data is None:
        raise HTTPException(status_code=404, detail="Tile not found (is default)")
    
    return Response(
        content=image_data,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=31536000",  # 1 year (versioned URLs)
        },
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
    
    Accepts PNG image data in the request body.
    Image must be exactly 32x32 pixels.
    """
    validate_coordinates(x, y)
    
    # Read request body
    image_data = await request.body()
    
    if not image_data:
        raise HTTPException(status_code=400, detail="No image data provided")
    
    # Validate PNG
    validate_png_image(image_data)
    
    # Save tile
    result = await tile_service.save_tile(x, y, image_data)
    
    # Broadcast update only to clients subscribed to this chunk
    chunk_id = tile_service.calculate_chunk_id(x, y)
    await manager.broadcast_to_chunk(chunk_id, {
        "type": "tile_update",
        "x": x,
        "y": y,
        "image": f"data:image/png;base64,{base64.b64encode(image_data).decode()}",
    })
    
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
    
    Removes the tile image and database record.
    """
    validate_coordinates(x, y)
    
    tile_id = tile_service.calculate_tile_id(x, y)
    deleted = await tile_service.delete_tile(x, y)
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Tile not found (already default)")
    
    return TileDeleteResponse(tile_id=tile_id)
