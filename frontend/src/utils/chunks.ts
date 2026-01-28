import { MOSAIC_CONFIG } from "../config";

const { TILE_SIZE, CHUNK_SIZE, GRID_WIDTH, GRID_HEIGHT } = MOSAIC_CONFIG;

// Maximum chunk coordinates (0-indexed)
const MAX_CHUNK_X = Math.ceil(GRID_WIDTH / CHUNK_SIZE) - 1;
const MAX_CHUNK_Y = Math.ceil(GRID_HEIGHT / CHUNK_SIZE) - 1;

/**
 * Calculate chunk ID from tile coordinates.
 * Format: "cx:cy" where cx and cy are chunk indices.
 */
export function getChunkId(tileX: number, tileY: number): string {
  const cx = Math.floor(tileX / CHUNK_SIZE);
  const cy = Math.floor(tileY / CHUNK_SIZE);
  return `${cx}:${cy}`;
}

/**
 * Calculate which chunks are visible in the current viewport.
 *
 * @param viewportX - Pixel offset from left edge (0 = no pan)
 * @param viewportY - Pixel offset from top edge (0 = no pan)
 * @param viewportWidth - Viewport width in pixels
 * @param viewportHeight - Viewport height in pixels
 * @returns Array of chunk IDs that are visible
 */
export function getVisibleChunks(
  viewportX: number,
  viewportY: number,
  viewportWidth: number,
  viewportHeight: number
): string[] {
  // Calculate tile range visible in viewport
  const startTileX = Math.max(0, Math.floor(viewportX / TILE_SIZE));
  const startTileY = Math.max(0, Math.floor(viewportY / TILE_SIZE));
  const endTileX = Math.min(GRID_WIDTH - 1, Math.ceil((viewportX + viewportWidth) / TILE_SIZE));
  const endTileY = Math.min(GRID_HEIGHT - 1, Math.ceil((viewportY + viewportHeight) / TILE_SIZE));

  // Convert to chunk range (clamped to valid range)
  const startChunkX = Math.max(0, Math.floor(startTileX / CHUNK_SIZE));
  const startChunkY = Math.max(0, Math.floor(startTileY / CHUNK_SIZE));
  const endChunkX = Math.min(MAX_CHUNK_X, Math.floor(endTileX / CHUNK_SIZE));
  const endChunkY = Math.min(MAX_CHUNK_Y, Math.floor(endTileY / CHUNK_SIZE));

  // Collect all visible chunks
  const chunks: string[] = [];
  for (let cx = startChunkX; cx <= endChunkX; cx++) {
    for (let cy = startChunkY; cy <= endChunkY; cy++) {
      chunks.push(`${cx}:${cy}`);
    }
  }

  return chunks;
}

/**
 * Calculate which chunks need to be subscribed/unsubscribed
 * when viewport changes.
 *
 * @param currentChunks - Currently subscribed chunks
 * @param newChunks - Chunks that should be subscribed
 * @returns Object with chunks to subscribe and unsubscribe
 */
export function diffChunkSubscriptions(
  currentChunks: string[],
  newChunks: string[]
): { subscribe: string[]; unsubscribe: string[] } {
  const currentSet = new Set(currentChunks);
  const newSet = new Set(newChunks);

  const subscribe = newChunks.filter((chunk) => !currentSet.has(chunk));
  const unsubscribe = currentChunks.filter((chunk) => !newSet.has(chunk));

  return { subscribe, unsubscribe };
}
