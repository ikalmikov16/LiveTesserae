export const MOSAIC_CONFIG = {
  GRID_WIDTH: 1000,
  GRID_HEIGHT: 1000,
  TILE_SIZE: 32,
  CHUNK_SIZE: 100,
} as const;

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

// Convert http(s) to ws(s) for WebSocket connection
export const WS_BASE_URL = API_BASE_URL.replace(/^http/, "ws");
