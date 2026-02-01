/**
 * Pixel data utilities for RGB byte array handling.
 *
 * Tile data format: 3072 bytes (32×32×3 RGB, row-major order)
 * - Pixel at (x, y): index = (y * 32 + x) * 3
 * - Bytes: [R, G, B] at indices [index, index+1, index+2]
 */

export const TILE_SIZE = 32;
export const PIXEL_DATA_SIZE = TILE_SIZE * TILE_SIZE * 3; // 3072 bytes

/**
 * Convert canvas ImageData (RGBA) to RGB byte array.
 *
 * @param imageData - Canvas ImageData (32×32, RGBA format)
 * @returns Uint8Array of 3072 bytes (RGB, no alpha)
 */
export function imageDataToRgb(imageData: ImageData): Uint8Array {
  const rgb = new Uint8Array(PIXEL_DATA_SIZE);

  for (let i = 0; i < TILE_SIZE * TILE_SIZE; i++) {
    const rgbIdx = i * 3;
    const rgbaIdx = i * 4;

    rgb[rgbIdx] = imageData.data[rgbaIdx]; // R
    rgb[rgbIdx + 1] = imageData.data[rgbaIdx + 1]; // G
    rgb[rgbIdx + 2] = imageData.data[rgbaIdx + 2]; // B
    // Alpha is ignored (always opaque)
  }

  return rgb;
}

/**
 * Convert RGB byte array to canvas ImageData.
 *
 * @param rgb - Uint8Array of 3072 bytes (RGB)
 * @returns ImageData suitable for canvas putImageData
 */
export function rgbToImageData(rgb: Uint8Array): ImageData {
  const imageData = new ImageData(TILE_SIZE, TILE_SIZE);

  for (let i = 0; i < TILE_SIZE * TILE_SIZE; i++) {
    const rgbIdx = i * 3;
    const rgbaIdx = i * 4;

    imageData.data[rgbaIdx] = rgb[rgbIdx]; // R
    imageData.data[rgbaIdx + 1] = rgb[rgbIdx + 1]; // G
    imageData.data[rgbaIdx + 2] = rgb[rgbIdx + 2]; // B
    imageData.data[rgbaIdx + 3] = 255; // A (always opaque)
  }

  return imageData;
}

/**
 * Decode base64 string to Uint8Array.
 *
 * @param base64 - Base64 encoded string
 * @returns Uint8Array of decoded bytes
 */
export function base64ToUint8Array(base64: string): Uint8Array {
  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);

  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  return bytes;
}

/**
 * Encode Uint8Array to base64 string.
 *
 * @param bytes - Uint8Array to encode
 * @returns Base64 encoded string
 */
export function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binaryString = "";
  for (let i = 0; i < bytes.length; i++) {
    binaryString += String.fromCharCode(bytes[i]);
  }
  return btoa(binaryString);
}

/**
 * Create default (white) tile pixel data.
 *
 * @returns Uint8Array of 3072 bytes, all 255 (white)
 */
export function createDefaultTileData(): Uint8Array {
  const rgb = new Uint8Array(PIXEL_DATA_SIZE);
  rgb.fill(255); // All white (R=255, G=255, B=255)
  return rgb;
}

/**
 * Validate pixel data size.
 *
 * @param data - Data to validate
 * @returns true if data is exactly 3072 bytes
 */
export function isValidPixelData(data: Uint8Array): boolean {
  return data.length === PIXEL_DATA_SIZE;
}
