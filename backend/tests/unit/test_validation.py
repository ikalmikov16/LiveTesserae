"""Tests for coordinate and pixel data validation helpers."""

import pytest
from fastapi import HTTPException

from app.api.tiles import RGB_DATA_SIZE, validate_coordinates, validate_pixel_data


def test_validate_coordinates_valid():
    validate_coordinates(0, 0)
    validate_coordinates(500, 500)
    validate_coordinates(999, 999)


def test_validate_coordinates_x_too_large():
    with pytest.raises(HTTPException) as exc:
        validate_coordinates(1000, 0)
    assert exc.value.status_code == 400


def test_validate_coordinates_y_negative():
    with pytest.raises(HTTPException) as exc:
        validate_coordinates(0, -1)
    assert exc.value.status_code == 400


def test_validate_pixel_data_correct_size():
    validate_pixel_data(bytes(RGB_DATA_SIZE))


def test_validate_pixel_data_too_small():
    with pytest.raises(HTTPException) as exc:
        validate_pixel_data(bytes(100))
    assert exc.value.status_code == 400


def test_validate_pixel_data_too_large():
    with pytest.raises(HTTPException) as exc:
        validate_pixel_data(bytes(4000))
    assert exc.value.status_code == 400


def test_validate_pixel_data_empty():
    with pytest.raises(HTTPException) as exc:
        validate_pixel_data(b"")
    assert exc.value.status_code == 400
