export const MOSAIC_CONFIG = {
  GRID_WIDTH: 1000,
  GRID_HEIGHT: 1000,
  TILE_SIZE: 32,
  CHUNK_SIZE: 100,
} as const;

/**
 * Zoom thresholds for render level selection, in screen pixels per tile.
 * Level 0 = single overview image, 1 = chunk images, 2 = individual tiles.
 */
export const LEVEL_0_THRESHOLD = 3;
export const LEVEL_1_THRESHOLD = 24;

export type RenderLevel = 0 | 1 | 2;

export function getRenderLevel(screenTileSize: number): RenderLevel {
  if (screenTileSize < LEVEL_0_THRESHOLD) return 0;
  if (screenTileSize < LEVEL_1_THRESHOLD) return 1;
  return 2;
}

/**
 * Most chunks one WebSocket may subscribe to.
 *
 * MUST NOT exceed `ws_max_subscriptions` in backend/app/config.py. The server
 * silently kept the first 50 of whatever arrived, so a client that asked for
 * all 100 chunks believed it held subscriptions the server had dropped — and
 * its next diff unsubscribed from exactly the 50 that did exist, leaving it
 * with none while the badge still read "Live".
 */
export const MAX_SUBSCRIBED_CHUNKS = 50;

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

if (
  !import.meta.env.VITE_API_BASE_URL &&
  typeof window !== "undefined" &&
  window.location.hostname !== "localhost" &&
  window.location.hostname !== "127.0.0.1"
) {
  console.warn(
    "[Live Tesserae] VITE_API_BASE_URL is not set — API calls will go to http://localhost:8000. " +
      "Set VITE_API_BASE_URL at build time for production."
  );
}

// Convert http(s) to ws(s) for WebSocket connection
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");

// CDN URL for chunk images (CloudFront)
// If set, chunks are loaded directly from CDN instead of through the API
export const CDN_BASE_URL = import.meta.env.VITE_CDN_BASE_URL || "";
