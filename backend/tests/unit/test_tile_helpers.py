"""Tests for tile ID calculation and parsing helpers."""

from app.services.tiles import calculate_chunk_id, calculate_tile_id, parse_tile_id


def test_calculate_tile_id():
    assert calculate_tile_id(512, 384) == "512:384"


def test_calculate_tile_id_origin():
    assert calculate_tile_id(0, 0) == "0:0"


def test_calculate_tile_id_max():
    assert calculate_tile_id(999, 999) == "999:999"


def test_calculate_chunk_id():
    assert calculate_chunk_id(512, 384) == "5:3"


def test_calculate_chunk_id_boundary():
    assert calculate_chunk_id(99, 99) == "0:0"
    assert calculate_chunk_id(100, 100) == "1:1"
    assert calculate_chunk_id(0, 0) == "0:0"
    assert calculate_chunk_id(999, 999) == "9:9"


def test_parse_tile_id():
    assert parse_tile_id("512:384") == (512, 384)
    assert parse_tile_id("0:0") == (0, 0)
    assert parse_tile_id("999:999") == (999, 999)


def test_parse_tile_id_roundtrip():
    for x, y in [(0, 0), (1, 1), (99, 99), (100, 100), (512, 384), (999, 999)]:
        assert parse_tile_id(calculate_tile_id(x, y)) == (x, y)
