import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { MOSAIC_CONFIG } from "../config";
import { useViewport } from "../hooks/useViewport";
import {
  loadChunkImage,
  loadOverviewImage,
  getOverviewVersion,
  getChunkVersion,
} from "../api/chunks";
import { tileLoader, TILE_CANCELLED } from "../utils/tileLoader";
import { rgbToImageData } from "../utils/pixels";
import { LRUCache } from "../utils/lruCache";
import { ZoomControls } from "./ZoomControls";
import type { TileCoordinates, TileWithPixels } from "../types";

const { TILE_SIZE, GRID_WIDTH, GRID_HEIGHT, CHUNK_SIZE } = MOSAIC_CONFIG;
const MOSAIC_WIDTH = GRID_WIDTH * TILE_SIZE;
const MOSAIC_HEIGHT = GRID_HEIGHT * TILE_SIZE;
const CHUNKS_PER_ROW = GRID_WIDTH / CHUNK_SIZE; // 10

// Zoom thresholds for level selection
const LEVEL_0_THRESHOLD = 3; // tile < 3px = show overview
const LEVEL_1_THRESHOLD = 24; // tile < 24px = show chunks

// Grid shows at Level 2 when tiles are at least this size
const GRID_THRESHOLD = 19; // ~60% zoom

// Cache size limits to prevent memory leaks
const MAX_TILE_CACHE_SIZE = 1000; // Max tiles to keep in memory (~3MB)
const MAX_CHUNK_CACHE_SIZE = 50; // Max chunks to keep in memory (~150MB max)

interface ChunkCache {
  image: HTMLImageElement;
  version: number;
}

interface TilePreview {
  x: number;
  y: number;
  pixelData: Uint8Array;
}

interface MosaicCanvasProps {
  onTileClick?: (coords: TileCoordinates) => void;
  tileUpdate?: TileWithPixels | null;
  onTileUpdateProcessed?: () => void;
  onViewportChange?: (offsetX: number, offsetY: number, zoom: number) => void;
  onOverviewLoad?: (image: HTMLImageElement) => void;
  navigateTo?: { x: number; y: number } | null;
  tilePreview?: TilePreview | null;
  selectedTile?: TileCoordinates | null;
}

export function MosaicCanvas({
  onTileClick,
  tileUpdate,
  onTileUpdateProcessed,
  onViewportChange,
  onOverviewLoad,
  navigateTo,
  tilePreview,
  selectedTile,
}: MosaicCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [canvasSize, setCanvasSize] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });
  // Use LRU cache for tile data to prevent unbounded memory growth
  const tileDataRef = useRef(new LRUCache<string, Uint8Array>(MAX_TILE_CACHE_SIZE));
  const [tileDataVersion, setTileDataVersion] = useState(0); // Trigger re-renders on cache updates
  const [showGrid, setShowGrid] = useState(true); // Toggle with 'G' key

  // Offscreen canvas for rendering RGB data
  const offscreenCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const getOffscreenCanvas = useCallback((): HTMLCanvasElement => {
    if (!offscreenCanvasRef.current) {
      offscreenCanvasRef.current = document.createElement("canvas");
      offscreenCanvasRef.current.width = TILE_SIZE;
      offscreenCanvasRef.current.height = TILE_SIZE;
    }
    return offscreenCanvasRef.current;
  }, []);

  // Render RGB tile data to canvas
  const renderTileData = useCallback(
    (
      ctx: CanvasRenderingContext2D,
      screenX: number,
      screenY: number,
      rgb: Uint8Array,
      screenTileSize: number
    ) => {
      const offscreen = getOffscreenCanvas();
      const offCtx = offscreen.getContext("2d")!;
      const imageData = rgbToImageData(rgb);
      offCtx.putImageData(imageData, 0, 0);

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(offscreen, screenX, screenY, screenTileSize, screenTileSize);
    },
    [getOffscreenCanvas]
  );

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
  // Use LRU cache for chunk images to prevent unbounded memory growth
  const chunkCacheRef = useRef(new LRUCache<string, ChunkCache>(MAX_CHUNK_CACHE_SIZE));
  const loadingChunksRef = useRef<Set<string>>(new Set());
  const [chunkCacheVersion, setChunkCacheVersion] = useState(0); // Trigger re-render when chunks load

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

  // Animation state for selection indicator pulse
  const [selectionPulse, setSelectionPulse] = useState(0);
  const selectionAnimationRef = useRef<number | null>(null);

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

      // Draw overview as base fallback (blurry but better than white)
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

      // Draw visible chunks as sharper preview layer (will be overdrawn by sharp tiles)
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

      // Draw loaded tile data on top (sharp tiles replace blurry chunk preview)
      tileDataRef.current.forEach((rgb, key) => {
        const [tileX, tileY] = key.split(":").map(Number);

        // Calculate exact pixel boundaries using rounding to avoid seams
        const x1 = Math.round((tileX * TILE_SIZE - offsetX) * zoom);
        const y1 = Math.round((tileY * TILE_SIZE - offsetY) * zoom);
        const x2 = Math.round(((tileX + 1) * TILE_SIZE - offsetX) * zoom);
        const y2 = Math.round(((tileY + 1) * TILE_SIZE - offsetY) * zoom);
        const tileW = x2 - x1;

        // Only draw if tile is visible in viewport
        if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
          renderTileData(ctx, x1, y1, rgb, tileW);
        }
      });

      // Draw tile preview overlay (live editing preview before save)
      if (tilePreview) {
        const x1 = Math.round((tilePreview.x * TILE_SIZE - offsetX) * zoom);
        const y1 = Math.round((tilePreview.y * TILE_SIZE - offsetY) * zoom);
        const x2 = Math.round(((tilePreview.x + 1) * TILE_SIZE - offsetX) * zoom);
        const y2 = Math.round(((tilePreview.y + 1) * TILE_SIZE - offsetY) * zoom);
        const tileW = x2 - x1;

        // Only draw if preview tile is visible
        if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
          renderTileData(ctx, x1, y1, tilePreview.pixelData, tileW);
        }
      }

      // Draw grid lines at Level 2 when zoomed in enough (toggleable with 'G' key)
      if (renderLevel === 2 && showGrid && screenTileSize >= GRID_THRESHOLD) {
        // Use "difference" blend mode so grid is always visible regardless of tile colors
        ctx.save();
        ctx.globalCompositeOperation = "difference";
        ctx.strokeStyle = "#ffffff"; // White + difference = inverts underlying colors
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
        ctx.restore();
      }
    }

    // Draw selection indicator for selected tile (on all levels, after everything else)
    const tileToHighlight =
      selectedTile || (tilePreview ? { x: tilePreview.x, y: tilePreview.y } : null);
    if (tileToHighlight) {
      const x1 = Math.round((tileToHighlight.x * TILE_SIZE - offsetX) * zoom);
      const y1 = Math.round((tileToHighlight.y * TILE_SIZE - offsetY) * zoom);
      const x2 = Math.round(((tileToHighlight.x + 1) * TILE_SIZE - offsetX) * zoom);
      const y2 = Math.round(((tileToHighlight.y + 1) * TILE_SIZE - offsetY) * zoom);
      const tileW = x2 - x1;
      const tileH = y2 - y1;

      // Only draw if tile is visible
      if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
        // Pulsing black border (opacity varies from 0.2 to 1.0)
        const opacity = 0.2 + selectionPulse * 0.8;
        ctx.strokeStyle = `rgba(0, 0, 0, ${opacity})`;
        ctx.lineWidth = 3;
        ctx.strokeRect(x1, y1, tileW, tileH);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- version counters trigger re-render when refs change
  }, [
    tileDataVersion,
    chunkCacheVersion,
    offsetX,
    offsetY,
    zoom,
    renderLevel,
    mosaicOverview,
    getVisibleChunks,
    screenTileSize,
    renderTileData,
    showGrid,
    tilePreview,
    selectedTile,
    selectionPulse,
  ]);

  // Animation loop for selection indicator pulse
  useEffect(() => {
    if (!selectedTile) {
      // No selection, stop animation
      if (selectionAnimationRef.current) {
        cancelAnimationFrame(selectionAnimationRef.current);
        selectionAnimationRef.current = null;
      }
      return;
    }

    // Start animation loop
    let startTime: number | null = null;
    const animate = (timestamp: number) => {
      if (!startTime) startTime = timestamp;
      const elapsed = timestamp - startTime;
      // Pulse every 1.5 seconds (using sine wave for smooth fade)
      const pulse = (Math.sin((elapsed / 750) * Math.PI) + 1) / 2; // 0 to 1
      setSelectionPulse(pulse);
      selectionAnimationRef.current = requestAnimationFrame(animate);
    };

    selectionAnimationRef.current = requestAnimationFrame(animate);

    return () => {
      if (selectionAnimationRef.current) {
        cancelAnimationFrame(selectionAnimationRef.current);
        selectionAnimationRef.current = null;
      }
    };
  }, [selectedTile]);

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

    // Handle tile pixel data for Level 2
    if (tileUpdate.pixelData) {
      tileDataRef.current.set(key, tileUpdate.pixelData!);
      setTileDataVersion((n) => n + 1); // Trigger re-render
      onTileUpdateProcessed?.();
    }

    // Reload chunk for Level 1 after a delay
    // Backend updates chunks asynchronously, so we wait for it to finish
    const reloadChunk = async () => {
      // Wait for backend to finish rendering (async background task)
      // Local saves need more time since the broadcast happens before render completes
      await new Promise((resolve) => setTimeout(resolve, 500));
      try {
        const versionInfo = await getChunkVersion(cx, cy);
        const img = await loadChunkImage(cx, cy, versionInfo.version);
        chunkCacheRef.current.set(chunkKey, { image: img, version: versionInfo.version });
        setChunkCacheVersion((n) => n + 1);
      } catch (error) {
        console.error(`Failed to reload chunk ${chunkKey}:`, error);
      }
    };
    reloadChunk();

    // Reload overview for Level 0 after a delay
    const reloadOverview = async () => {
      // Wait for backend to finish rendering (async background task)
      await new Promise((resolve) => setTimeout(resolve, 600));
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

  // RAF batching - prevent multiple drawCanvas calls per frame
  const rafIdRef = useRef<number | null>(null);
  const pendingDrawRef = useRef(false);

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

  // Load missing or outdated chunks when at Level 1 or Level 2 (used as fallback preview)
  // Debounced to prevent excessive requests during fast panning
  useEffect(() => {
    if (renderLevel === 0) return;

    // Debounce chunk loading to avoid overwhelming the server during fast panning
    const timeoutId = setTimeout(() => {
      const visibleChunks = getVisibleChunks();
      const cache = chunkCacheRef.current;
      const loading = loadingChunksRef.current;

      visibleChunks.forEach(({ cx, cy }) => {
        const key = `${cx}_${cy}`;
        if (loading.has(key)) return;

        const cached = cache.get(key);

        // Always check server version (even if cached) to detect updates
        loading.add(key);

        getChunkVersion(cx, cy)
          .then((versionInfo) => {
            // If cached version matches server, skip reload
            if (cached && cached.version === versionInfo.version) {
              loading.delete(key);
              return null;
            }

            // Load new version
            return loadChunkImage(cx, cy, versionInfo.version).then((img) => ({
              img,
              version: versionInfo.version,
            }));
          })
          .then((result) => {
            if (result) {
              cache.set(key, { image: result.img, version: result.version });
              loading.delete(key);
              setChunkCacheVersion((n) => n + 1); // Trigger re-render
            }
          })
          .catch((error) => {
            console.error(`Failed to load chunk ${key}:`, error);
            loading.delete(key);
          });
      });
    }, 100); // 100ms debounce for chunk loading

    return () => clearTimeout(timeoutId);
  }, [renderLevel, getVisibleChunks]);

  // Load missing tiles when at Level 2 (with debouncing and queue)
  useEffect(() => {
    if (renderLevel !== 2) {
      // Cancel pending requests when leaving Level 2
      tileLoader.cancelAll();
      // Clear loading set immediately to avoid stale state when returning to Level 2
      loadingTilesRef.current.clear();
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

      // Immediately clear cancelled tiles from loading set (don't wait for promise resolution)
      // This prevents race condition where pan-back happens before promises resolve
      for (const key of loading) {
        if (!visibleKeys.has(key)) {
          loading.delete(key);
        }
      }

      // Sort tiles by distance from viewport center for priority loading
      const centerX = offsetX + canvasSize.width / zoom / 2;
      const centerY = offsetY + canvasSize.height / zoom / 2;

      const sortedTiles = [...visibleTiles].sort((a, b) => {
        const distA = Math.abs(a.x * TILE_SIZE - centerX) + Math.abs(a.y * TILE_SIZE - centerY);
        const distB = Math.abs(b.x * TILE_SIZE - centerX) + Math.abs(b.y * TILE_SIZE - centerY);
        return distA - distB;
      });

      const tileCache = tileDataRef.current;

      sortedTiles.forEach(({ x, y }) => {
        const key = getTileKey(x, y);
        // Skip if already loaded, loading, or known to not exist
        if (tileCache.has(key) || loading.has(key) || nonExistent.has(key)) return;

        loading.add(key);

        tileLoader
          .loadTile(x, y)
          .then((result) => {
            loading.delete(key);

            if (result === TILE_CANCELLED) {
              // Request was cancelled (e.g., during panning) - will retry on next render
              return;
            }

            if (result === null) {
              // Tile doesn't exist (404) - mark as non-existent
              nonExistent.add(key);
              return;
            }

            // Got valid tile data - add to LRU cache
            tileCache.set(key, result);
            setTileDataVersion((n) => n + 1); // Trigger re-render
          })
          .catch(() => {
            // Request failed, just remove from loading (will retry)
            loading.delete(key);
          });
      });
    }, 50); // 50ms debounce

    return () => clearTimeout(timeoutId);
  }, [
    renderLevel,
    getVisibleTiles,
    // tileDataVersion not needed - we check the ref directly
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

  // Schedule a redraw using requestAnimationFrame
  // Batches multiple draw requests into a single frame
  const scheduleRedraw = useCallback(() => {
    if (pendingDrawRef.current) return; // Already scheduled

    pendingDrawRef.current = true;
    rafIdRef.current = requestAnimationFrame(() => {
      pendingDrawRef.current = false;
      rafIdRef.current = null;
      drawCanvas();
    });
  }, [drawCanvas]);

  // Cleanup RAF on unmount
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, []);

  // Redraw canvas when dependencies change (only after canvas is ready)
  // Uses RAF batching to prevent multiple redraws per frame
  useEffect(() => {
    if (isCanvasReady) {
      scheduleRedraw();
    }
  }, [isCanvasReady, scheduleRedraw]);

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

  // Keyboard shortcut for grid toggle (G key)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Only handle 'G' key without modifiers, and not when typing in an input
      if (
        (e.key === "g" || e.key === "G") &&
        !e.metaKey &&
        !e.ctrlKey &&
        !e.altKey &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement)
      ) {
        setShowGrid((prev) => !prev);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

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
        showGrid={showGrid}
        onToggleGrid={() => setShowGrid((prev) => !prev)}
      />
    </>
  );
}
