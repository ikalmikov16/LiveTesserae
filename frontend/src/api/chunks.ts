/**
 * Chunks API for multi-level rendering.
 *
 * Provides functions to fetch:
 * - Individual chunk preview images (Level 1)
 * - Full mosaic overview image (Level 0)
 * - Version information for cache busting
 */

import { API_BASE_URL, CDN_BASE_URL } from "../config";

export interface ChunkVersion {
  cx: number;
  cy: number;
  version: number;
}

export interface OverviewVersion {
  version: number;
  stale: boolean;
}

/**
 * Get the URL for a chunk image with optional version for cache busting.
 * Uses CDN if configured, otherwise falls back to API.
 */
export function getChunkImageUrl(cx: number, cy: number, version?: number): string {
  const versionParam = version ? `?v=${version}` : "";
  if (CDN_BASE_URL) {
    return `${CDN_BASE_URL}/${cx}_${cy}.webp${versionParam}`;
  }
  return `${API_BASE_URL}/api/chunks/${cx}/${cy}${versionParam}`;
}

/**
 * Get the current version of a chunk.
 */
export async function getChunkVersion(cx: number, cy: number): Promise<ChunkVersion> {
  const response = await fetch(`${API_BASE_URL}/api/chunks/${cx}/${cy}/version`, {
    cache: "no-store", // Always get fresh version to avoid stale cache busting
  });
  if (!response.ok) throw new Error("Failed to get chunk version");
  return response.json();
}

/**
 * Get the URL for the mosaic overview image with optional version.
 * Uses CDN if configured, otherwise falls back to API.
 */
export function getMosaicOverviewUrl(version?: number): string {
  const versionParam = version ? `?v=${version}` : "";
  if (CDN_BASE_URL) {
    return `${CDN_BASE_URL}/mosaic_overview.webp${versionParam}`;
  }
  return `${API_BASE_URL}/api/chunks/overview${versionParam}`;
}

/**
 * Get the current version and stale status of the overview.
 */
export async function getOverviewVersion(): Promise<OverviewVersion> {
  const response = await fetch(`${API_BASE_URL}/api/chunks/overview/version`, {
    cache: "no-store", // Always get fresh version to avoid stale cache busting
  });
  if (!response.ok) throw new Error("Failed to get overview version");
  return response.json();
}

/**
 * Load a chunk image and return it as an HTMLImageElement.
 */
export function loadChunkImage(
  cx: number,
  cy: number,
  version?: number
): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Failed to load chunk ${cx},${cy}`));
    img.src = getChunkImageUrl(cx, cy, version);
  });
}

/**
 * Load the mosaic overview image and return it as an HTMLImageElement.
 */
export function loadOverviewImage(version?: number): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Failed to load overview"));
    img.src = getMosaicOverviewUrl(version);
  });
}
