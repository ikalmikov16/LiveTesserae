import { API_BASE_URL } from "../config";
import { getSessionId } from "../utils/session";

/**
 * Save tile pixel data to the backend.
 * PUT /api/tiles/{x}/{y}
 */
export async function saveTile(
  x: number,
  y: number,
  pixelData: Uint8Array
): Promise<{ tile_id: string; chunk_id: string; version: number }> {
  // Create a proper ArrayBuffer copy for fetch body
  const buffer = new ArrayBuffer(pixelData.length);
  new Uint8Array(buffer).set(pixelData);

  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
    method: "PUT",
    body: buffer,
    headers: {
      "Content-Type": "application/octet-stream",
      "X-Session-Id": getSessionId(),
    },
  });

  if (response.status === 429) {
    throw new Error("You're painting too fast! Wait a moment and try again.");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to save tile: ${response.status}`);
  }

  return response.json();
}

/**
 * Get tile pixel data from the backend.
 * GET /api/tiles/{x}/{y}
 * Returns null if tile is default (404).
 */
export async function getTilePixels(x: number, y: number): Promise<Uint8Array | null> {
  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
    // Revalidate every time, but let a 304 reuse the cached body. See tileLoader.
    cache: "no-cache",
  });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new Error(`Failed to get tile: ${response.status}`);
  }

  const buffer = await response.arrayBuffer();
  return new Uint8Array(buffer);
}

/**
 * Check if a tile exists (is not default).
 * Uses HEAD request for efficiency.
 */
export async function tileExists(x: number, y: number): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
    method: "HEAD",
    cache: "no-cache",
  });

  return response.ok;
}
