import { API_BASE_URL } from "../config";

export interface MosaicStats {
  edited_tiles: number;
  total_edits: number;
  unique_editors: number;
  pixels_painted: number;
}

export async function getMosaicStats(): Promise<MosaicStats> {
  const response = await fetch(`${API_BASE_URL}/api/mosaic/stats`);
  if (!response.ok) {
    throw new Error(`Failed to fetch stats: ${response.status}`);
  }
  return response.json();
}
