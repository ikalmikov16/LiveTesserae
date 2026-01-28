-- Live Tesserae Database Schema
-- Tiles and Chunks tables for the collaborative mosaic

-- Tiles table: stores metadata for edited tiles only (sparse storage)
-- Note: image_path is NOT stored - it's computed from coordinates as:
--       tiles/{chunk_x}/{chunk_y}/{x}_{y}.png
CREATE TABLE IF NOT EXISTS tiles (
    tile_id VARCHAR(11) PRIMARY KEY,  -- "x:y" format, max "999:999"
    chunk_id VARCHAR(7) NOT NULL,     -- "cx:cy" format for efficient queries
    version INTEGER DEFAULT 1,
    updated_at TIMESTAMP DEFAULT NOW()
);

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
