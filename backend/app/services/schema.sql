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
