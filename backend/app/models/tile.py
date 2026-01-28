from datetime import datetime

from pydantic import BaseModel, Field

from app.config import settings


class TileCoordinates(BaseModel):
    """Validated tile coordinates."""

    x: int = Field(ge=0, lt=settings.grid_width, description="X coordinate (0-999)")
    y: int = Field(ge=0, lt=settings.grid_height, description="Y coordinate (0-999)")


class TileResponse(BaseModel):
    """Response model for tile metadata."""

    tile_id: str = Field(description="Tile ID in 'x:y' format")
    chunk_id: str = Field(description="Chunk ID in 'cx:cy' format")
    x: int = Field(description="X coordinate")
    y: int = Field(description="Y coordinate")
    version: int = Field(description="Tile version number")
    updated_at: datetime = Field(description="Last update timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "tile_id": "512:384",
                "chunk_id": "5:3",
                "x": 512,
                "y": 384,
                "version": 1,
                "updated_at": "2024-01-26T12:00:00Z",
            }
        }


class TileSaveResponse(BaseModel):
    """Response after saving a tile."""

    tile_id: str
    chunk_id: str
    version: int
    message: str = "Tile saved successfully"


class TileDeleteResponse(BaseModel):
    """Response after deleting a tile."""

    tile_id: str
    message: str = "Tile reset to default"
