"""Tests for Pydantic request/response models."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models.tile import (
    TileCoordinates,
    TileDeleteResponse,
    TileResponse,
    TileSaveResponse,
)


def test_tile_response_valid():
    r = TileResponse(
        tile_id="512:384",
        chunk_id="5:3",
        x=512,
        y=384,
        version=1,
        updated_at=datetime.now(),
    )
    assert r.tile_id == "512:384"
    assert r.chunk_id == "5:3"
    assert r.x == 512
    assert r.version == 1


def test_tile_response_missing_fields():
    with pytest.raises(ValidationError):
        TileResponse(tile_id="5:3")


def test_tile_save_response_defaults():
    r = TileSaveResponse(tile_id="5:3", chunk_id="0:0", version=1)
    assert r.message == "Tile saved successfully"


def test_tile_delete_response_defaults():
    r = TileDeleteResponse(tile_id="5:3")
    assert r.message == "Tile reset to default"


def test_tile_coordinates_bounds():
    with pytest.raises(ValidationError):
        TileCoordinates(x=1000, y=0)
    with pytest.raises(ValidationError):
        TileCoordinates(x=0, y=1000)


def test_tile_coordinates_boundary_values():
    c1 = TileCoordinates(x=0, y=0)
    assert c1.x == 0

    c2 = TileCoordinates(x=999, y=999)
    assert c2.x == 999

    with pytest.raises(ValidationError):
        TileCoordinates(x=-1, y=0)
