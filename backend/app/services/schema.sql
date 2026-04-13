-- Live Tesserae Database Schema
-- Tiles and Chunks tables for the collaborative mosaic

-- Tiles table: stores pixel data for edited tiles only (sparse storage)
-- pixel_data stores raw RGB bytes (3072 bytes = 32×32×3)
CREATE TABLE IF NOT EXISTS tiles (
    tile_id VARCHAR(11) PRIMARY KEY,  -- "x:y" format, max "999:999"
    chunk_id VARCHAR(7) NOT NULL,     -- "cx:cy" format for efficient queries
    pixel_data BYTEA,                 -- 3072 bytes of RGB data (32×32×3), NULL = default white
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Migration: Add pixel_data column to existing tables
-- Run this if upgrading from a previous version:
-- ALTER TABLE tiles ADD COLUMN IF NOT EXISTS pixel_data BYTEA;

-- Index for efficient chunk queries (loading all tiles in a chunk)
CREATE INDEX IF NOT EXISTS idx_tiles_chunk ON tiles(chunk_id);

-- Index for finding recently updated tiles
CREATE INDEX IF NOT EXISTS idx_tiles_updated ON tiles(updated_at);

-- Chunks table: tracks chunk render status and versions
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id VARCHAR(7) PRIMARY KEY,  -- "cx:cy" format
    version INTEGER DEFAULT 0,
    dirty BOOLEAN DEFAULT FALSE,
    rendered_at TIMESTAMP
);

-- Index for finding dirty chunks that need re-rendering
CREATE INDEX IF NOT EXISTS idx_chunks_dirty ON chunks(dirty) WHERE dirty = TRUE;

-- Edit log: append-only log of every tile edit for stats tracking
-- session_id is a client-generated UUID stored in localStorage (no auth needed)
CREATE TABLE IF NOT EXISTS edit_log (
    id BIGSERIAL PRIMARY KEY,
    tile_id VARCHAR(11) NOT NULL,
    session_id VARCHAR(36) NOT NULL,
    edited_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_edit_log_session ON edit_log(session_id);
CREATE INDEX IF NOT EXISTS idx_edit_log_edited_at ON edit_log(edited_at);
