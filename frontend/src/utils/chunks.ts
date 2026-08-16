import { MAX_SUBSCRIBED_CHUNKS, MOSAIC_CONFIG } from "../config";

const { TILE_SIZE, CHUNK_SIZE, GRID_WIDTH, GRID_HEIGHT } = MOSAIC_CONFIG;

// World pixels along one edge of a chunk
const CHUNK_WORLD_SIZE = CHUNK_SIZE * TILE_SIZE;

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
 * Trim a set of visible chunks to what one connection may actually hold,
 * keeping the ones nearest the viewport centre.
 *
 * This must happen BEFORE diffing against the current subscriptions. The server
 * caps each connection at MAX_SUBSCRIBED_CHUNKS and drops the rest, so sending
 * more means the client's idea of its subscriptions silently diverges from the
 * server's — and the next diff then unsubscribes from chunks the server holds
 * while subscribing to nothing.
 *
 * @param chunks - Visible chunk IDs ("cx:cy")
 * @param centerX - Viewport centre X in world pixels
 * @param centerY - Viewport centre Y in world pixels
 * @param max - Cap (defaults to the server's limit)
 * @returns At most `max` chunk IDs, nearest the centre first
 */
export function selectSubscribableChunks(
  chunks: string[],
  centerX: number,
  centerY: number,
  max: number = MAX_SUBSCRIBED_CHUNKS
): string[] {
  if (chunks.length <= max) return chunks;

  const distance = (chunkId: string): number => {
    const [cx, cy] = chunkId.split(":").map(Number);
    const dx = (cx + 0.5) * CHUNK_WORLD_SIZE - centerX;
    const dy = (cy + 0.5) * CHUNK_WORLD_SIZE - centerY;
    return dx * dx + dy * dy;
  };

  return [...chunks].sort((a, b) => distance(a) - distance(b)).slice(0, max);
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
