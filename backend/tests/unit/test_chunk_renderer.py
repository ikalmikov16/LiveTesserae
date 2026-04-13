"""Tests for PIL-based chunk and overview rendering."""

import io

import pytest
from PIL import Image

from app.config import settings
from app.services.chunk_renderer import (
    CHUNK_PREVIEW_SIZE,
    MOSAIC_PREVIEW_SIZE,
    _get_chunk_bounds_in_overview,
    _get_tile_bounds_in_chunk,
    _render_chunk_sync,
    _render_mosaic_overview_sync,
    _update_chunk_tile_sync,
    _update_overview_chunk_sync,
    rgb_bytes_to_image,
)
from app.services.tiles import parse_tile_id
from tests.conftest import BLUE_TILE, RED_TILE, make_solid_rgb


def open_webp(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def make_test_chunk_webp(color=(255, 0, 0)):
    img = Image.new("RGB", (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE), color)
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


# ── rgb_bytes_to_image ──────────────────────────────────────────────────


def test_rgb_bytes_to_image_dimensions(valid_pixel_data):
    img = rgb_bytes_to_image(valid_pixel_data)
    assert img.size == (32, 32)
    assert img.mode == "RGB"


def test_rgb_bytes_to_image_red_tile():
    img = rgb_bytes_to_image(RED_TILE)
    assert img.getpixel((0, 0)) == (255, 0, 0)
    assert img.getpixel((31, 31)) == (255, 0, 0)
    assert img.getpixel((16, 16)) == (255, 0, 0)


def test_rgb_bytes_to_image_pixel_order():
    data = bytearray(3072)
    # pixel (0,0) = index 0 → (1,2,3)
    data[0], data[1], data[2] = 1, 2, 3
    # pixel (1,0) = index 1 → (4,5,6)
    data[3], data[4], data[5] = 4, 5, 6
    # pixel (0,1) = index 32 → (10,20,30)
    idx = 32 * 3
    data[idx], data[idx + 1], data[idx + 2] = 10, 20, 30

    img = rgb_bytes_to_image(bytes(data))
    assert img.getpixel((0, 0)) == (1, 2, 3)
    assert img.getpixel((1, 0)) == (4, 5, 6)
    assert img.getpixel((0, 1)) == (10, 20, 30)


# ── tile bounds in chunk ────────────────────────────────────────────────


def test_get_tile_bounds_in_chunk_origin():
    x, y, w, h = _get_tile_bounds_in_chunk(0, 0)
    assert x == 0
    assert y == 0
    assert w > 0
    assert h > 0


def test_get_tile_bounds_in_chunk_last():
    x, y, w, h = _get_tile_bounds_in_chunk(
        settings.chunk_size - 1, settings.chunk_size - 1
    )
    assert x + w == CHUNK_PREVIEW_SIZE
    assert y + h == CHUNK_PREVIEW_SIZE


def test_get_tile_bounds_no_gaps():
    total_width = 0
    prev_end = 0
    for i in range(settings.chunk_size):
        x, _, w, _ = _get_tile_bounds_in_chunk(i, 0)
        assert (
            x == prev_end
        ), f"Gap or overlap at tile {i}: expected x={prev_end}, got {x}"
        prev_end = x + w
        total_width = x + w
    assert total_width == CHUNK_PREVIEW_SIZE


# ── chunk bounds in overview ────────────────────────────────────────────


def test_get_chunk_bounds_in_overview_origin():
    x, y, w, h = _get_chunk_bounds_in_overview(0, 0)
    assert x == 0
    assert y == 0
    assert w > 0
    assert h > 0


def test_get_chunk_bounds_in_overview_last():
    chunks_per_row = settings.grid_width // settings.chunk_size
    x, y, w, h = _get_chunk_bounds_in_overview(chunks_per_row - 1, chunks_per_row - 1)
    assert x + w == MOSAIC_PREVIEW_SIZE
    assert y + h == MOSAIC_PREVIEW_SIZE


def test_get_chunk_bounds_no_gaps():
    chunks_per_row = settings.grid_width // settings.chunk_size
    prev_end = 0
    for i in range(chunks_per_row):
        x, _, w, _ = _get_chunk_bounds_in_overview(i, 0)
        assert x == prev_end, f"Gap or overlap at chunk {i}"
        prev_end = x + w
    assert prev_end == MOSAIC_PREVIEW_SIZE


# ── _update_chunk_tile_sync ─────────────────────────────────────────────


def test_update_chunk_tile_sync_new_chunk():
    result = _update_chunk_tile_sync(None, 0, 0, 5, 5, RED_TILE)
    img = open_webp(result)
    assert img.size == (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE)

    # Tile at (5,5) in chunk (0,0) → local (5,5) should have red-ish pixels
    px, py, _, _ = _get_tile_bounds_in_chunk(5, 5)
    pixel = img.getpixel((px + 1, py + 1))
    assert pixel[0] > 200, f"Expected red-ish pixel, got {pixel}"


def test_update_chunk_tile_sync_existing():
    # Place red tile at local (0,0)
    chunk_v1 = _update_chunk_tile_sync(None, 0, 0, 0, 0, RED_TILE)
    # Place blue tile at local (1,0)
    chunk_v2 = _update_chunk_tile_sync(chunk_v1, 0, 0, 1, 0, BLUE_TILE)

    img = open_webp(chunk_v2)
    # Red tile at (0,0) should still be there
    px0, py0, _, _ = _get_tile_bounds_in_chunk(0, 0)
    pixel_red = img.getpixel((px0 + 1, py0 + 1))
    assert pixel_red[0] > 200, f"Red tile lost, got {pixel_red}"

    # Blue tile at (1,0) should be present
    px1, py1, _, _ = _get_tile_bounds_in_chunk(1, 0)
    pixel_blue = img.getpixel((px1 + 1, py1 + 1))
    assert pixel_blue[2] > 200, f"Blue tile not found, got {pixel_blue}"


def test_update_chunk_tile_sync_clear():
    chunk = _update_chunk_tile_sync(None, 0, 0, 0, 0, RED_TILE)
    cleared = _update_chunk_tile_sync(chunk, 0, 0, 0, 0, None)

    img = open_webp(cleared)
    px, py, _, _ = _get_tile_bounds_in_chunk(0, 0)
    pixel = img.getpixel((px + 1, py + 1))
    assert pixel == (255, 255, 255), f"Expected white after clear, got {pixel}"


def test_update_chunk_tile_sync_output_is_webp():
    result = _update_chunk_tile_sync(None, 0, 0, 0, 0, RED_TILE)
    img = Image.open(io.BytesIO(result))
    assert img.format == "WEBP"


# ── _update_overview_chunk_sync ─────────────────────────────────────────


def test_update_overview_chunk_sync_new():
    chunk_webp = make_test_chunk_webp(color=(255, 0, 0))
    result = _update_overview_chunk_sync(None, 0, 0, chunk_webp)
    img = open_webp(result)
    assert img.size == (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE)


def test_update_overview_chunk_sync_existing():
    red_chunk = make_test_chunk_webp(color=(255, 0, 0))
    blue_chunk = make_test_chunk_webp(color=(0, 0, 255))

    overview_v1 = _update_overview_chunk_sync(None, 0, 0, red_chunk)
    overview_v2 = _update_overview_chunk_sync(overview_v1, 1, 1, blue_chunk)

    img = open_webp(overview_v2)
    # Chunk (0,0) region should still have red
    px0, py0, _, _ = _get_chunk_bounds_in_overview(0, 0)
    pixel = img.getpixel((px0 + 10, py0 + 10))
    assert pixel[0] > 200, f"Red chunk lost, got {pixel}"


# ── _render_chunk_sync ──────────────────────────────────────────────────


def test_render_chunk_sync_empty():
    data, count = _render_chunk_sync(0, 0, [], parse_tile_id)
    assert count == 0
    img = open_webp(data)
    assert img.size == (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE)
    assert img.getpixel((0, 0)) == (255, 255, 255)


def test_render_chunk_sync_with_tiles():
    rows = [
        {"tile_id": "0:0", "pixel_data": RED_TILE},
        {"tile_id": "1:0", "pixel_data": BLUE_TILE},
    ]
    data, count = _render_chunk_sync(0, 0, rows, parse_tile_id)
    assert count == 2
    img = open_webp(data)
    assert img.size == (CHUNK_PREVIEW_SIZE, CHUNK_PREVIEW_SIZE)


# ── _render_mosaic_overview_sync ────────────────────────────────────────


def test_render_mosaic_overview_sync_empty():
    data, count = _render_mosaic_overview_sync([])
    assert count == 0
    img = open_webp(data)
    assert img.size == (MOSAIC_PREVIEW_SIZE, MOSAIC_PREVIEW_SIZE)
    assert img.getpixel((0, 0)) == (255, 255, 255)
