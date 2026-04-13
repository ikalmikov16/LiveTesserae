export const MOSAIC_CONFIG = {
  GRID_WIDTH: 1000,
  GRID_HEIGHT: 1000,
  TILE_SIZE: 32,
  CHUNK_SIZE: 100,
} as const;

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
