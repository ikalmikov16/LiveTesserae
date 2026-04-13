"""Tests for chunk version tracking logic."""

import json

import pytest

from app.services.storage import (
    get_chunk_version,
    get_chunk_versions_path,
    get_overview_version,
    increment_chunk_version,
    increment_overview_version,
    is_overview_stale,
)


async def test_initial_chunk_version_is_zero(tmp_storage):
    v = await get_chunk_version(0, 0)
    assert v == 0


async def test_increment_chunk_version(tmp_storage):
    v1 = await increment_chunk_version(0, 0)
    assert v1 == 1
    v2 = await increment_chunk_version(0, 0)
    assert v2 == 2


async def test_increment_marks_overview_stale(tmp_storage):
    await increment_chunk_version(0, 0)
    assert await is_overview_stale() is True


async def test_increment_overview_version(tmp_storage):
    v1 = await increment_overview_version()
    assert v1 == 1
    v2 = await increment_overview_version()
    assert v2 == 2


async def test_overview_increment_clears_stale(tmp_storage):
    await increment_chunk_version(0, 0)
    assert await is_overview_stale() is True
    await increment_overview_version()
    assert await is_overview_stale() is False


async def test_multiple_chunks_independent(tmp_storage):
    await increment_chunk_version(0, 0)
    await increment_chunk_version(0, 0)
    await increment_chunk_version(1, 1)

    assert await get_chunk_version(0, 0) == 2
    assert await get_chunk_version(1, 1) == 1


async def test_versions_persist_across_loads(tmp_storage):
    await increment_chunk_version(5, 5)
    v = await get_chunk_version(5, 5)
    assert v == 1


async def test_corrupt_versions_file_recovery(tmp_storage):
    versions_path = get_chunk_versions_path()
    versions_path.parent.mkdir(parents=True, exist_ok=True)
    versions_path.write_text("NOT VALID JSON {{{")

    v = await get_chunk_version(0, 0)
    assert v == 0


async def test_missing_versions_file(tmp_storage):
    v = await get_chunk_version(0, 0)
    assert v == 0
    stale = await is_overview_stale()
    assert stale is True
