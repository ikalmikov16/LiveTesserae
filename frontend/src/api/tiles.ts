import { API_BASE_URL } from "../config";

/**
 * Save a tile image to the backend.
 * PUT /api/tiles/{x}/{y}
 */
export async function saveTile(
  x: number,
  y: number,
  pngBlob: Blob
): Promise<{ tile_id: string; chunk_id: string; version: number }> {
  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
    method: "PUT",
    body: pngBlob,
    headers: {
      "Content-Type": "image/png",
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unknown error" }));
    throw new Error(error.detail || `Failed to save tile: ${response.status}`);
  }

  return response.json();
}

/**
 * Get a tile image from the backend.
 * GET /api/tiles/{x}/{y}
 * Returns null if tile is default (404).
 */
export async function getTileImage(x: number, y: number): Promise<Blob | null> {
  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`);

  if (response.status === 404) {
    // Tile doesn't exist (is default)
    return null;
  }

  if (!response.ok) {
    throw new Error(`Failed to get tile: ${response.status}`);
  }

  return response.blob();
}

/**
 * Get tile image as a data URL for loading into canvas.
 * Returns null if tile is default (404).
 */
export async function getTileImageUrl(x: number, y: number): Promise<string | null> {
  const blob = await getTileImage(x, y);
  if (!blob) return null;

  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

/**
 * Check if a tile exists (is not default).
 * Uses HEAD request for efficiency.
 */
export async function tileExists(x: number, y: number): Promise<boolean> {
  const response = await fetch(`${API_BASE_URL}/api/tiles/${x}/${y}`, {
    method: "HEAD",
  });

  return response.ok;
}
