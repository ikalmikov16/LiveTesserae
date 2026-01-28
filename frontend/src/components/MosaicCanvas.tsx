import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { MOSAIC_CONFIG } from "../config";
import { useViewport } from "../hooks/useViewport";
import {
  loadChunkImage,
  loadOverviewImage,
  getOverviewVersion,
  getChunkVersion,
} from "../api/chunks";
import { tileLoader } from "../utils/tileLoader";
import { ZoomControls } from "./ZoomControls";
import type { TileCoordinates, TileWithImage } from "../types";

const { TILE_SIZE, GRID_WIDTH, GRID_HEIGHT, CHUNK_SIZE } = MOSAIC_CONFIG;
const MOSAIC_WIDTH = GRID_WIDTH * TILE_SIZE;
const MOSAIC_HEIGHT = GRID_HEIGHT * TILE_SIZE;
const CHUNKS_PER_ROW = GRID_WIDTH / CHUNK_SIZE; // 10

// Zoom thresholds for level selection
const LEVEL_0_THRESHOLD = 3; // tile < 3px = show overview
const LEVEL_1_THRESHOLD = 24; // tile < 24px = show chunks

interface ChunkCache {
  image: HTMLImageElement;
  version: number;
}

interface MosaicCanvasProps {
  onTileClick?: (coords: TileCoordinates) => void;
  tileUpdate?: TileWithImage | null;
  onTileUpdateProcessed?: () => void;
  onViewportChange?: (offsetX: number, offsetY: number, zoom: number) => void;
  onOverviewLoad?: (image: HTMLImageElement) => void;
  navigateTo?: { x: number; y: number } | null;
}

export function MosaicCanvas({
  onTileClick,
  tileUpdate,
  onTileUpdateProcessed,
  onViewportChange,
  onOverviewLoad,
  navigateTo,
}: MosaicCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [canvasSize, setCanvasSize] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  const [tileImages, setTileImages] = useState<Map<string, HTMLImageElement>>(new Map());

  // Viewport state with pan/zoom
  const { viewport, pan, zoomAt, setZoom, setOffset, resetView, minZoom, maxZoom } = useViewport(
    canvasSize.width,
    canvasSize.height
  );
  const { offsetX, offsetY, zoom } = viewport;

  // Drag state
  const [isDragging, setIsDragging] = useState(false);
  const lastMousePos = useRef({ x: 0, y: 0 });
  const dragStartPos = useRef({ x: 0, y: 0 });

  // Handle external navigation requests (from MiniMap)
  useEffect(() => {
    if (navigateTo) {
      setOffset(navigateTo.x, navigateTo.y);
    }
  }, [navigateTo, setOffset]);

  // Multi-level rendering state
  const [mosaicOverview, setMosaicOverview] = useState<HTMLImageElement | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(false);
  const chunkCacheRef = useRef<Map<string, ChunkCache>>(new Map());
  const loadingChunksRef = useRef<Set<string>>(new Set());
  const [, forceUpdate] = useState(0); // Trigger re-render when chunks load

  // Determine render level based on zoom
  const screenTileSize = TILE_SIZE * zoom;
  const renderLevel = useMemo(() => {
    if (screenTileSize < LEVEL_0_THRESHOLD) return 0;
    if (screenTileSize < LEVEL_1_THRESHOLD) return 1;
    return 2;
  }, [screenTileSize]);

  // Create a key for the tile coordinates
  const getTileKey = (x: number, y: number) => `${x}:${y}`;

  // Calculate visible chunks for Level 1
  const getVisibleChunks = useCallback((): { cx: number; cy: number }[] => {
    if (!canvasRef.current) return [];

    const canvasWidth = canvasRef.current.width;
    const canvasHeight = canvasRef.current.height;

    // Calculate visible range
    const startCx = Math.max(0, Math.floor(offsetX / (CHUNK_SIZE * TILE_SIZE)));
    const startCy = Math.max(0, Math.floor(offsetY / (CHUNK_SIZE * TILE_SIZE)));
    const endCx = Math.min(
      CHUNKS_PER_ROW - 1,
      Math.floor((offsetX + canvasWidth / zoom) / (CHUNK_SIZE * TILE_SIZE))
    );
    const endCy = Math.min(
      CHUNKS_PER_ROW - 1,
      Math.floor((offsetY + canvasHeight / zoom) / (CHUNK_SIZE * TILE_SIZE))
    );

    const chunks: { cx: number; cy: number }[] = [];
    for (let cx = startCx; cx <= endCx; cx++) {
      for (let cy = startCy; cy <= endCy; cy++) {
        chunks.push({ cx, cy });
      }
    }
    return chunks;
  }, [offsetX, offsetY, zoom]);

  // Calculate visible tiles for Level 2
  const getVisibleTiles = useCallback((): { x: number; y: number }[] => {
    if (!canvasRef.current) return [];

    const canvasWidth = canvasRef.current.width;
    const canvasHeight = canvasRef.current.height;

    // Calculate visible range
    const startX = Math.max(0, Math.floor(offsetX / TILE_SIZE));
    const startY = Math.max(0, Math.floor(offsetY / TILE_SIZE));
    const endX = Math.min(GRID_WIDTH - 1, Math.floor((offsetX + canvasWidth / zoom) / TILE_SIZE));
    const endY = Math.min(GRID_HEIGHT - 1, Math.floor((offsetY + canvasHeight / zoom) / TILE_SIZE));

    const tiles: { x: number; y: number }[] = [];
    for (let x = startX; x <= endX; x++) {
      for (let y = startY; y <= endY; y++) {
        tiles.push({ x, y });
      }
    }
    return tiles;
  }, [offsetX, offsetY, zoom]);

  // Track tiles being loaded and tiles that don't exist (404)
  const loadingTilesRef = useRef<Set<string>>(new Set());
  const nonExistentTilesRef = useRef<Set<string>>(new Set());

  // Draw the canvas with viewport transform
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const width = canvas.width;
    const height = canvas.height;

    // Clear with dark background (visible around mosaic at low zoom)
    ctx.fillStyle = "#1a1a1a";
    ctx.fillRect(0, 0, width, height);

    // Calculate mosaic position on screen
    const mosaicScreenX = (0 - offsetX) * zoom;
    const mosaicScreenY = (0 - offsetY) * zoom;
    const mosaicScreenW = MOSAIC_WIDTH * zoom;
    const mosaicScreenH = MOSAIC_HEIGHT * zoom;

    if (renderLevel === 0 && mosaicOverview) {
      // Level 0: Draw single overview image
      ctx.drawImage(
        mosaicOverview,
        Math.round(mosaicScreenX),
        Math.round(mosaicScreenY),
        Math.round(mosaicScreenW),
        Math.round(mosaicScreenH)
      );
    } else if (renderLevel === 1) {
      // Level 1: Draw chunk images
      const cache = chunkCacheRef.current;
      const chunkWorldSize = CHUNK_SIZE * TILE_SIZE;

      // First draw overview as fallback (blurry preview while chunks load)
      if (mosaicOverview) {
        ctx.drawImage(
          mosaicOverview,
          Math.round(mosaicScreenX),
          Math.round(mosaicScreenY),
          Math.round(mosaicScreenW),
          Math.round(mosaicScreenH)
        );
      } else {
        // No overview yet, draw white background
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(
          Math.round(mosaicScreenX),
          Math.round(mosaicScreenY),
          Math.round(mosaicScreenW),
          Math.round(mosaicScreenH)
        );
      }

      // Draw loaded chunks on top (sharper than overview)
      getVisibleChunks().forEach(({ cx, cy }) => {
        const key = `${cx}_${cy}`;
        const cached = cache.get(key);

        if (cached) {
          // Calculate exact pixel boundaries using rounding to avoid seams
          const x1 = Math.round((cx * chunkWorldSize - offsetX) * zoom);
          const y1 = Math.round((cy * chunkWorldSize - offsetY) * zoom);
          const x2 = Math.round(((cx + 1) * chunkWorldSize - offsetX) * zoom);
          const y2 = Math.round(((cy + 1) * chunkWorldSize - offsetY) * zoom);
          ctx.drawImage(cached.image, x1, y1, x2 - x1, y2 - y1);
        }
        // If not cached, overview is showing as fallback - no need for placeholder
      });
    } else {
      // Level 2: Draw individual tiles
      // First, draw chunk images as blurry preview (instant visual feedback)
      const cache = chunkCacheRef.current;
      const chunkWorldSize = CHUNK_SIZE * TILE_SIZE;

      // Draw white mosaic area as base
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(
        Math.round(mosaicScreenX),
        Math.round(mosaicScreenY),
        Math.round(mosaicScreenW),
        Math.round(mosaicScreenH)
      );

      // Draw visible chunks as preview layer (will be overdrawn by sharp tiles)
      getVisibleChunks().forEach(({ cx, cy }) => {
        const cached = cache.get(`${cx}_${cy}`);
        if (cached) {
          const x1 = Math.round((cx * chunkWorldSize - offsetX) * zoom);
          const y1 = Math.round((cy * chunkWorldSize - offsetY) * zoom);
          const x2 = Math.round(((cx + 1) * chunkWorldSize - offsetX) * zoom);
          const y2 = Math.round(((cy + 1) * chunkWorldSize - offsetY) * zoom);
          ctx.drawImage(cached.image, x1, y1, x2 - x1, y2 - y1);
        }
      });

      // Draw loaded tile images on top (sharp tiles replace blurry chunk preview)
      tileImages.forEach((img, key) => {
        const [tileX, tileY] = key.split(":").map(Number);

        // Calculate exact pixel boundaries using rounding to avoid seams
        const x1 = Math.round((tileX * TILE_SIZE - offsetX) * zoom);
        const y1 = Math.round((tileY * TILE_SIZE - offsetY) * zoom);
        const x2 = Math.round(((tileX + 1) * TILE_SIZE - offsetX) * zoom);
        const y2 = Math.round(((tileY + 1) * TILE_SIZE - offsetY) * zoom);
        const tileW = x2 - x1;
        const tileH = y2 - y1;

        // Only draw if tile is visible in viewport
        if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
          ctx.drawImage(img, x1, y1, tileW, tileH);
        }
      });

      // Draw grid lines only at Level 2 (individual tiles) and if tiles are large enough
      if (renderLevel === 2 && screenTileSize >= 8) {
        ctx.strokeStyle = "#e0e0e0";
        ctx.lineWidth = 1;

        // Calculate visible tile range
        const startTileX = Math.max(0, Math.floor(offsetX / TILE_SIZE));
        const startTileY = Math.max(0, Math.floor(offsetY / TILE_SIZE));
        const endTileX = Math.min(GRID_WIDTH, Math.ceil((offsetX + width / zoom) / TILE_SIZE));
        const endTileY = Math.min(GRID_HEIGHT, Math.ceil((offsetY + height / zoom) / TILE_SIZE));

        // Draw vertical lines
        ctx.beginPath();
        for (let i = startTileX; i <= endTileX; i++) {
          const screenX = (i * TILE_SIZE - offsetX) * zoom;
          ctx.moveTo(screenX + 0.5, Math.max(0, mosaicScreenY));
          ctx.lineTo(screenX + 0.5, Math.min(height, mosaicScreenY + mosaicScreenH));
        }
        ctx.stroke();

        // Draw horizontal lines
        ctx.beginPath();
        for (let i = startTileY; i <= endTileY; i++) {
          const screenY = (i * TILE_SIZE - offsetY) * zoom;
          ctx.moveTo(Math.max(0, mosaicScreenX), screenY + 0.5);
          ctx.lineTo(Math.min(width, mosaicScreenX + mosaicScreenW), screenY + 0.5);
        }
        ctx.stroke();
      }
    }
  }, [
    tileImages,
    offsetX,
    offsetY,
    zoom,
    renderLevel,
    mosaicOverview,
    getVisibleChunks,
    screenTileSize,
  ]);

  // Process tile updates (from WebSocket or local saves)
  useEffect(() => {
    if (!tileUpdate) return;

    const key = getTileKey(tileUpdate.x, tileUpdate.y);

    // Calculate affected chunk
    const cx = Math.floor(tileUpdate.x / CHUNK_SIZE);
    const cy = Math.floor(tileUpdate.y / CHUNK_SIZE);
    const chunkKey = `${cx}_${cy}`;

    // Clear non-existent flag in case tile was previously 404
    nonExistentTilesRef.current.delete(key);

    // Handle tile image for Level 2
    if (tileUpdate.imageData) {
      const img = new Image();

      img.onload = () => {
        setTileImages((prev) => {
          const newMap = new Map(prev);
          newMap.set(key, img);
          return newMap;
        });
        onTileUpdateProcessed?.();
      };

      img.onerror = () => {
        console.error(`Failed to load tile image (${tileUpdate.x}, ${tileUpdate.y})`);
        onTileUpdateProcessed?.();
      };

      img.src = tileUpdate.imageData;
    }

    // Reload chunk for Level 1 after a short delay
    // Backend updates chunks asynchronously, so we wait a bit before fetching
    const reloadChunk = async () => {
      // Wait for backend to finish rendering (async background task)
      await new Promise((resolve) => setTimeout(resolve, 200));
      try {
        const versionInfo = await getChunkVersion(cx, cy);
        const img = await loadChunkImage(cx, cy, versionInfo.version);
        chunkCacheRef.current.set(chunkKey, { image: img, version: versionInfo.version });
        forceUpdate((n) => n + 1);
      } catch (error) {
        console.error(`Failed to reload chunk ${chunkKey}:`, error);
      }
    };
    reloadChunk();

    // Reload overview for Level 0 after a short delay
    const reloadOverview = async () => {
      // Wait for backend to finish rendering (async background task)
      await new Promise((resolve) => setTimeout(resolve, 250));
      try {
        const versionInfo = await getOverviewVersion();
        const img = await loadOverviewImage(versionInfo.version);
        setMosaicOverview(img);
        onOverviewLoad?.(img);
      } catch (error) {
        console.error("Failed to reload overview:", error);
      }
    };
    reloadOverview();
  }, [tileUpdate, onTileUpdateProcessed, onOverviewLoad]);

  // Track if canvas has been initialized
  const [isCanvasReady, setIsCanvasReady] = useState(false);

  // Load overview on mount (for initial page load)
  useEffect(() => {
    if (overviewLoading || mosaicOverview) return;

    setOverviewLoading(true);

    const loadOverview = async () => {
      try {
        const versionInfo = await getOverviewVersion();
        const img = await loadOverviewImage(versionInfo.version);
        setMosaicOverview(img);
        onOverviewLoad?.(img);
      } catch (error) {
        console.error("Failed to load overview:", error);
      } finally {
        setOverviewLoading(false);
      }
    };

    loadOverview();
  }, [overviewLoading, mosaicOverview, onOverviewLoad]);

  // Load missing chunks when at Level 1 or Level 2 (used as fallback preview)
  useEffect(() => {
    if (renderLevel === 0) return;

    const visibleChunks = getVisibleChunks();
    const cache = chunkCacheRef.current;
    const loading = loadingChunksRef.current;

    visibleChunks.forEach(({ cx, cy }) => {
      const key = `${cx}_${cy}`;
      if (cache.has(key) || loading.has(key)) return;

      loading.add(key);

      // Fetch version first for cache busting, then load image
      getChunkVersion(cx, cy)
        .then((versionInfo) => {
          return loadChunkImage(cx, cy, versionInfo.version).then((img) => ({
            img,
            version: versionInfo.version,
          }));
        })
        .then(({ img, version }) => {
          cache.set(key, { image: img, version });
          loading.delete(key);
          forceUpdate((n) => n + 1); // Trigger re-render
        })
        .catch((error) => {
          console.error(`Failed to load chunk ${key}:`, error);
          loading.delete(key);
        });
    });
  }, [renderLevel, getVisibleChunks]);

  // Load missing tiles when at Level 2 (with debouncing and queue)
  useEffect(() => {
    if (renderLevel !== 2) {
      // Cancel pending requests when leaving Level 2
      tileLoader.cancelAll();
      return;
    }

    // Debounce tile loading to avoid overwhelming the server during fast panning
    const timeoutId = setTimeout(() => {
      const visibleTiles = getVisibleTiles();
      const loading = loadingTilesRef.current;
      const nonExistent = nonExistentTilesRef.current;

      // Build set of visible tile keys for cancellation
      const visibleKeys = new Set(visibleTiles.map(({ x, y }) => getTileKey(x, y)));

      // Cancel requests for tiles no longer visible
      tileLoader.cancelNotIn(visibleKeys);

      // Sort tiles by distance from viewport center for priority loading
      const centerX = offsetX + canvasSize.width / zoom / 2;
      const centerY = offsetY + canvasSize.height / zoom / 2;

      const sortedTiles = [...visibleTiles].sort((a, b) => {
        const distA = Math.abs(a.x * TILE_SIZE - centerX) + Math.abs(a.y * TILE_SIZE - centerY);
        const distB = Math.abs(b.x * TILE_SIZE - centerX) + Math.abs(b.y * TILE_SIZE - centerY);
        return distA - distB;
      });

      sortedTiles.forEach(({ x, y }) => {
        const key = getTileKey(x, y);
        // Skip if already loaded, loading, or known to not exist
        if (tileImages.has(key) || loading.has(key) || nonExistent.has(key)) return;

        loading.add(key);

        tileLoader
          .loadTile(x, y)
          .then((dataUrl) => {
            loading.delete(key);
            if (dataUrl === null) {
              // Tile doesn't exist (404) or was cancelled
              nonExistent.add(key);
              return;
            }

            const img = new Image();
            img.onload = () => {
              setTileImages((prev) => {
                const newMap = new Map(prev);
                newMap.set(key, img);
                return newMap;
              });
            };
            img.src = dataUrl;
          })
          .catch(() => {
            // Request was cancelled or failed, just remove from loading
            loading.delete(key);
          });
      });
    }, 50); // 50ms debounce

    return () => clearTimeout(timeoutId);
  }, [
    renderLevel,
    getVisibleTiles,
    tileImages,
    offsetX,
    offsetY,
    zoom,
    canvasSize.width,
    canvasSize.height,
  ]);

  // Handle window resize and initial canvas setup
  useEffect(() => {
    const handleResize = () => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      setCanvasSize({ width: window.innerWidth, height: window.innerHeight });
      setIsCanvasReady(true);
    };

    // Initial setup
    handleResize();

    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // Reset view to fit-to-screen on initial load
  const hasInitialized = useRef(false);
  useEffect(() => {
    if (isCanvasReady && !hasInitialized.current) {
      hasInitialized.current = true;
      resetView();
    }
  }, [isCanvasReady, resetView]);

  // Redraw canvas when dependencies change (only after canvas is ready)
  useEffect(() => {
    if (isCanvasReady) {
      drawCanvas();
    }
  }, [isCanvasReady, drawCanvas]);

  // Global mouse handlers during drag
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - lastMousePos.current.x;
      const deltaY = e.clientY - lastMousePos.current.y;
      lastMousePos.current = { x: e.clientX, y: e.clientY };
      pan(deltaX, deltaY);
    };

    const handleMouseUp = () => setIsDragging(false);

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, pan]);

  // Wheel handler for zooming/panning (native event for passive: false)
  // - Trackpad pinch (ctrlKey=true): zoom
  // - Mouse wheel (deltaMode=1, line-based): zoom
  // - Trackpad 2-finger swipe (ctrlKey=false, deltaMode=0): pan
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();

      const rect = canvas.getBoundingClientRect();
      const canvasX = e.clientX - rect.left;
      const canvasY = e.clientY - rect.top;

      // Pinch gesture on trackpad sends ctrlKey=true
      // Mouse wheel typically has deltaMode=1 (line-based)
      const isPinch = e.ctrlKey;
      const isMouseWheel = e.deltaMode === 1;

      if (isPinch || isMouseWheel) {
        // Zoom
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        zoomAt(canvasX, canvasY, factor);
      } else {
        // Pan (trackpad 2-finger swipe)
        // pan() already converts screen pixels to world coordinates
        pan(-e.deltaX, -e.deltaY);
      }
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [zoomAt, pan]);

  // Notify parent of viewport changes immediately (for minimap responsiveness)
  useEffect(() => {
    onViewportChange?.(offsetX, offsetY, zoom);
  }, [offsetX, offsetY, zoom, onViewportChange]);

  // Mouse down handler for drag start
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    lastMousePos.current = { x: e.clientX, y: e.clientY };
    dragStartPos.current = { x: e.clientX, y: e.clientY };
  };

  // Click handler - distinguish from drag
  const handleClick = (e: React.MouseEvent) => {
    // Only trigger click if mouse didn't move much (not a drag)
    const dx = e.clientX - dragStartPos.current.x;
    const dy = e.clientY - dragStartPos.current.y;
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    const rect = canvas.getBoundingClientRect();
    const canvasX = e.clientX - rect.left;
    const canvasY = e.clientY - rect.top;

    // Convert screen to world coordinates
    const worldX = canvasX / zoom + offsetX;
    const worldY = canvasY / zoom + offsetY;

    // Check if click is within mosaic bounds
    if (worldX < 0 || worldX >= MOSAIC_WIDTH || worldY < 0 || worldY >= MOSAIC_HEIGHT) {
      return; // Clicked outside mosaic
    }

    const tileX = Math.floor(worldX / TILE_SIZE);
    const tileY = Math.floor(worldY / TILE_SIZE);

    // Ensure tile coordinates are valid
    if (tileX >= 0 && tileX < GRID_WIDTH && tileY >= 0 && tileY < GRID_HEIGHT) {
      onTileClick?.({ x: tileX, y: tileY });
    }
  };

  // Zoom controls
  return (
    <>
      <canvas
        ref={canvasRef}
        onMouseDown={handleMouseDown}
        onClick={handleClick}
        style={{ cursor: isDragging ? "grabbing" : "grab" }}
      />
      <ZoomControls
        zoom={zoom}
        minZoom={minZoom}
        maxZoom={maxZoom}
        onZoomChange={setZoom}
        onReset={resetView}
      />
    </>
  );
}
