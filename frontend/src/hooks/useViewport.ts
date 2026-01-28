import { useState, useCallback, useMemo } from "react";
import { MOSAIC_CONFIG } from "../config";

const { GRID_WIDTH, GRID_HEIGHT, TILE_SIZE } = MOSAIC_CONFIG;
const MOSAIC_WIDTH = GRID_WIDTH * TILE_SIZE;
const MOSAIC_HEIGHT = GRID_HEIGHT * TILE_SIZE;
const MAX_ZOOM = 4;
const PADDING = 40;

export interface ViewportState {
  offsetX: number;
  offsetY: number;
  zoom: number;
}

function calculateFitToScreenViewport(canvasWidth: number, canvasHeight: number): ViewportState {
  const availableWidth = canvasWidth - PADDING * 2;
  const availableHeight = canvasHeight - PADDING * 2;
  const fitZoom = Math.min(availableWidth / MOSAIC_WIDTH, availableHeight / MOSAIC_HEIGHT);
  const scaledWidth = MOSAIC_WIDTH * fitZoom;
  const scaledHeight = MOSAIC_HEIGHT * fitZoom;
  return {
    offsetX: -(canvasWidth - scaledWidth) / 2 / fitZoom,
    offsetY: -(canvasHeight - scaledHeight) / 2 / fitZoom,
    zoom: fitZoom,
  };
}

export function useViewport(canvasWidth: number, canvasHeight: number) {
  // Lazy initial state - only runs once on mount
  const [viewport, setViewport] = useState<ViewportState>(() =>
    calculateFitToScreenViewport(canvasWidth, canvasHeight)
  );

  // Calculate MIN_ZOOM dynamically (fit-to-screen zoom)
  const minZoom = useMemo(() => {
    const availableWidth = canvasWidth - PADDING * 2;
    const availableHeight = canvasHeight - PADDING * 2;
    return Math.min(availableWidth / MOSAIC_WIDTH, availableHeight / MOSAIC_HEIGHT);
  }, [canvasWidth, canvasHeight]);

  // Clamp offset to keep mosaic partially visible
  const clampOffset = useCallback(
    (offsetX: number, offsetY: number, zoom: number) => {
      // Allow panning until only 20% of canvas shows the mosaic (as margin)
      const marginX = (canvasWidth * 0.8) / zoom;
      const marginY = (canvasHeight * 0.8) / zoom;

      // Min offset: mosaic right/bottom edge at canvas left/top + margin
      const minOffsetX = -marginX;
      const minOffsetY = -marginY;
      // Max offset: mosaic left/top edge at canvas right/bottom - margin
      const maxOffsetX = MOSAIC_WIDTH - canvasWidth / zoom + marginX;
      const maxOffsetY = MOSAIC_HEIGHT - canvasHeight / zoom + marginY;

      return {
        offsetX: Math.max(minOffsetX, Math.min(maxOffsetX, offsetX)),
        offsetY: Math.max(minOffsetY, Math.min(maxOffsetY, offsetY)),
      };
    },
    [canvasWidth, canvasHeight]
  );

  // Stable function reference with useCallback
  const pan = useCallback(
    (deltaX: number, deltaY: number) => {
      setViewport((v) => {
        const newOffsetX = v.offsetX - deltaX / v.zoom;
        const newOffsetY = v.offsetY - deltaY / v.zoom;
        const clamped = clampOffset(newOffsetX, newOffsetY, v.zoom);
        return { ...v, ...clamped };
      });
    },
    [clampOffset]
  );

  // Zoom toward a screen point, keeping that point stationary
  const zoomAt = useCallback(
    (screenX: number, screenY: number, factor: number) => {
      setViewport((v) => {
        const newZoom = Math.max(minZoom, Math.min(MAX_ZOOM, v.zoom * factor));
        if (newZoom === v.zoom) return v; // No change

        // Convert screen point to world before zoom
        const worldX = screenX / v.zoom + v.offsetX;
        const worldY = screenY / v.zoom + v.offsetY;
        // Calculate new offset to keep that world point at same screen position
        const newOffsetX = worldX - screenX / newZoom;
        const newOffsetY = worldY - screenY / newZoom;
        const clamped = clampOffset(newOffsetX, newOffsetY, newZoom);
        return { ...clamped, zoom: newZoom };
      });
    },
    [minZoom, clampOffset]
  );

  // Set zoom absolutely, keeping center of canvas fixed
  const setZoom = useCallback(
    (newZoom: number) => {
      setViewport((v) => {
        const clampedZoom = Math.max(minZoom, Math.min(MAX_ZOOM, newZoom));
        if (clampedZoom === v.zoom) return v;

        // Keep center of canvas at same world position
        const centerX = canvasWidth / 2;
        const centerY = canvasHeight / 2;
        const worldX = centerX / v.zoom + v.offsetX;
        const worldY = centerY / v.zoom + v.offsetY;
        const newOffsetX = worldX - centerX / clampedZoom;
        const newOffsetY = worldY - centerY / clampedZoom;
        const clamped = clampOffset(newOffsetX, newOffsetY, clampedZoom);
        return { ...clamped, zoom: clampedZoom };
      });
    },
    [minZoom, canvasWidth, canvasHeight, clampOffset]
  );

  // Set offset directly (for minimap navigation)
  const setOffset = useCallback(
    (newOffsetX: number, newOffsetY: number) => {
      setViewport((v) => {
        const clamped = clampOffset(newOffsetX, newOffsetY, v.zoom);
        return { ...v, ...clamped };
      });
    },
    [clampOffset]
  );

  // Reset to fit-to-screen view
  const resetView = useCallback(() => {
    setViewport(calculateFitToScreenViewport(canvasWidth, canvasHeight));
  }, [canvasWidth, canvasHeight]);

  return { viewport, pan, zoomAt, setZoom, setOffset, resetView, minZoom, maxZoom: MAX_ZOOM };
}
