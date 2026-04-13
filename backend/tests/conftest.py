"""Root conftest — shared fixtures for all tests."""

import os

import pytest


def make_solid_rgb(r: int, g: int, b: int) -> bytes:
    """Create 3072-byte solid color tile (32x32x3 RGB)."""
    return bytes([r, g, b] * 1024)


RED_TILE = make_solid_rgb(255, 0, 0)
WHITE_TILE = make_solid_rgb(255, 255, 255)
BLUE_TILE = make_solid_rgb(0, 0, 255)


@pytest.fixture(scope="session")
def valid_pixel_data() -> bytes:
    """3072 bytes of red RGB pixel data."""
    return RED_TILE


@pytest.fixture(scope="session")
def white_pixel_data() -> bytes:
    """3072 bytes of white RGB pixel data."""
    return WHITE_TILE


@pytest.fixture
def random_pixel_data() -> bytes:
    """Random 3072-byte RGB pixel data (unique per test)."""
    return os.urandom(3072)


@pytest.fixture(scope="session")
def sample_coords() -> list[tuple[int, int]]:
    """Common test coordinates: origin, middle, max."""
    return [(0, 0), (512, 384), (999, 999)]
