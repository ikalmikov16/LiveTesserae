"""Tests for WebSocket chunk ID validation."""

from app.websocket.routes import validate_chunk_ids


def test_validate_valid_chunk_ids():
    result = validate_chunk_ids(["0:0", "5:5", "9:9"])
    assert result == ["0:0", "5:5", "9:9"]


def test_validate_invalid_format():
    result = validate_chunk_ids(["abc", "0-0", "::", "0:", ""])
    assert result == []


def test_validate_out_of_bounds():
    result = validate_chunk_ids(["10:0", "0:10", "99:99"])
    assert result == []


def test_validate_non_string_elements():
    result = validate_chunk_ids([123, None, True, ["0:0"]])
    assert result == []


def test_validate_caps_at_max_per_message():
    ids = [f"{i % 10}:{i // 10}" for i in range(100)]
    result = validate_chunk_ids(ids)
    assert len(result) <= 50


def test_validate_mixed_valid_invalid():
    result = validate_chunk_ids(["0:0", "bad", "1:1", "99:0"])
    assert result == ["0:0", "1:1"]
