export const MOSAIC_CONFIG = {
  GRID_WIDTH: 1000,
  GRID_HEIGHT: 1000,
  TILE_SIZE: 32,
  CHUNK_SIZE: 100,
} as const;

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Convert http(s) to ws(s) for WebSocket connection
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");

// CDN URL for chunk images (CloudFront)
// If set, chunks are loaded directly from CDN instead of through the API
export const CDN_BASE_URL = import.meta.env.VITE_CDN_BASE_URL || "";

// Helper to get chunk URL (uses CDN if configured, otherwise API)
export function getChunkUrl(cx: number, cy: number, version: number): string {
  if (CDN_BASE_URL) {
    return `${CDN_BASE_URL}/${cx}_${cy}.webp?v=${version}`;
  }
  return `${API_BASE_URL}/api/chunks/${cx}/${cy}?v=${version}`;
}

// Helper to get overview URL
export function getOverviewUrl(version: number): string {
  if (CDN_BASE_URL) {
    return `${CDN_BASE_URL}/mosaic_overview.webp?v=${version}`;
  }
  return `${API_BASE_URL}/api/mosaic/overview?v=${version}`;
}
