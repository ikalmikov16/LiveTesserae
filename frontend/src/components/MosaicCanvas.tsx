import { useRef, useEffect, useCallback, useState, useMemo } from "react";
import { MOSAIC_CONFIG, getRenderLevel, LEVEL_1_THRESHOLD } from "../config";
import { useViewport } from "../hooks/useViewport";
import { useOverviewImage } from "../hooks/useOverviewImage";
import { loadChunkImage, getChunkVersion } from "../api/chunks";
import { tileLoader, TILE_CANCELLED } from "../utils/tileLoader";
import { rgbToImageData } from "../utils/pixels";
import { LRUCache } from "../utils/lruCache";
import { classifyWheel, type WheelLike } from "../utils/wheel";
import { useCanvasGestures } from "../hooks/useCanvasGestures";
import { ZoomControls } from "./ZoomControls";
import "./MosaicCanvas.css";
import type {
  TileCoordinates,
  TileWithPixels,
  ChunkUpdatedMessage,
  OverviewUpdatedMessage,
} from "../types";

const { TILE_SIZE, GRID_WIDTH, GRID_HEIGHT, CHUNK_SIZE } = MOSAIC_CONFIG;
const MOSAIC_WIDTH = GRID_WIDTH * TILE_SIZE;
const MOSAIC_HEIGHT = GRID_HEIGHT * TILE_SIZE;
const CHUNKS_PER_ROW = GRID_WIDTH / CHUNK_SIZE; // 10

// Grid shows at Level 2 when tiles are at least this size
const GRID_THRESHOLD = 19; // ~60% zoom

// Cap the backing store at 2x device pixels. A 390x844 phone at DPR 3
// composites ~2.96M pixels per frame; DPR 2 is (2/3)^2 = 44% of that for
// nearly all of the sharpness. Tune this after measuring on real hardware.
const MAX_DEVICE_PIXEL_RATIO = 2;

const getDevicePixelRatio = () => Math.min(window.devicePixelRatio || 1, MAX_DEVICE_PIXEL_RATIO);

// How far a double tap or double click zooms in.
//
// A phone's fit-to-screen is ~0.31 px/tile, so reaching the 24 px/tile editing
// gate is a ~77x journey: seven doubles at 2x, five at 3x. Pinch is the primary
// way to cover that ground; this is the coarse assist and should feel like it.
const DOUBLE_TAP_ZOOM_FACTOR = 3;

// Cache size limits to prevent memory leaks
//
// Floor for the tile cache. The real capacity is computed from the viewport by
// tileCacheCapacity() below — a fixed 1000 was smaller than the Level 2 working
// set on any ordinary screen (a 1440x900 window needs ~2300 tiles the moment it
// enters Level 2), so tiles evicted each other as fast as they loaded. Most of
// the viewport then fell back to the upscaled chunk image with a shifting
// patchwork of real tiles over it, which reads as tiles rendering wrongly —
// while opening the editor, which fetches the tile directly, looked correct.
const MIN_TILE_CACHE_SIZE = 1000;

/**
 * Tiles to keep for a given canvas, in CSS pixels.
 *
 * Sized at LEVEL_1_THRESHOLD px per tile — the lowest zoom that draws
 * individual tiles, and therefore the most tiles the viewport can ever ask for
 * — plus a quarter for panning headroom. This is a cap, not an allocation: a
 * phone only ever stores the few hundred tiles it actually loads, so a generous
 * bound costs small screens nothing. At 3072 B per tile, 1440x900 works out
 * around 9 MB and a 4K display around 56 MB.
 */
function tileCacheCapacity(cssWidth: number, cssHeight: number): number {
  const perRow = Math.ceil(cssWidth / LEVEL_1_THRESHOLD) + 1;
  const perColumn = Math.ceil(cssHeight / LEVEL_1_THRESHOLD) + 1;
  return Math.max(MIN_TILE_CACHE_SIZE, Math.ceil(perRow * perColumn * 1.25));
}
// Max chunks to keep in memory. Chunk images are 2000x2000 (CHUNK_PREVIEW_SIZE
// in chunk_renderer.py), so a decoded RGBA bitmap is 2000*2000*4 = 16 MB and
// 50 of them is a ~800 MB ceiling — not the ~150 MB this comment used to claim,
// which corresponded to 0.72 bytes/pixel and no raster format. It is a ceiling
// rather than a resident figure because the browser owns the decoded data for an
// HTMLImageElement and may drop it when the image is not being painted; that is
// also why switching to ImageBitmap is not the obvious win it looks like, since
// an ImageBitmap is pinned until close(). See input-and-mobile.md phase 3.
const MAX_CHUNK_CACHE_SIZE = 50;

interface ChunkCache {
  image: HTMLImageElement;
  version: number;
}

/**
 * A cached Level 2 tile.
 *
 * `bitmap` is null between the tile arriving and its decode resolving. The
 * entry is inserted immediately anyway so the loader counts the tile as held
 * and does not re-request it every pass; the chunk image underneath covers the
 * square for those few milliseconds.
 */
interface TileEntry {
  bitmap: ImageBitmap | null;
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
  chunkUpdate?: ChunkUpdatedMessage | null;
  onChunkUpdateProcessed?: () => void;
  overviewUpdate?: OverviewUpdatedMessage | null;
  onOverviewUpdateProcessed?: () => void;
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
  chunkUpdate,
  onChunkUpdateProcessed,
  overviewUpdate,
  onOverviewUpdateProcessed,
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
  // Use LRU cache for tile data to prevent unbounded memory growth.
  //
  // Holds a decoded, IMMUTABLE ImageBitmap per tile rather than raw bytes.
  // Immutability is the point: nothing can mutate a bitmap between queuing a
  // draw and the GPU executing it, so the drawn pixels are the tile's own on
  // every engine. It is also far cheaper — decoding happens once when the tile
  // arrives instead of once per tile per frame.
  //
  // The entry is an object so the bitmap can be attached in place after the
  // async decode without re-inserting the key and disturbing LRU order, and so
  // a decode that finishes after its entry was evicted or replaced can detect
  // that by identity and close its bitmap instead of resurrecting it.
  const tileDataRef = useRef(
    new LRUCache<string, TileEntry>(
      tileCacheCapacity(window.innerWidth, window.innerHeight),
      // An ImageBitmap stays resident until closed; the GC will not do it.
      (entry) => entry.bitmap?.close()
    )
  );
  const [tileDataVersion, setTileDataVersion] = useState(0); // Trigger re-renders on cache updates
  const [showGrid, setShowGrid] = useState(true); // Toggle with 'G' key

  // Scratch canvas for the LIVE EDIT PREVIEW only — never for cached tiles.
  //
  // Cached tiles used to go through a single shared 32x32 canvas: putImageData
  // then drawImage, once per tile, ~600 times per frame. That is only correct
  // if drawImage snapshots its source. Chrome/Skia does. WebKit hands drawImage
  // a live reference to the source surface, so on iOS the queued draws could
  // resolve against whatever that one surface held later — which is why Level 2
  // showed the wrong tile's pixels in cell after cell, changing on every
  // repaint, while Levels 0 and 1 (real images, never mutated) were fine.
  //
  // The preview keeps a scratch canvas because its bytes change on every
  // brush stroke, so caching a bitmap per stroke would be worse. It is safe
  // here for the same two reasons the tile editor is correct on the same
  // device: it is drawn exactly ONCE per frame, so there is no second draw to
  // alias against, and willReadFrequently forces an unaccelerated CPU buffer,
  // off the GPU path entirely.
  const previewCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const renderPreviewTile = useCallback(
    (
      ctx: CanvasRenderingContext2D,
      screenX: number,
      screenY: number,
      rgb: Uint8Array,
      width: number,
      height: number
    ) => {
      if (!previewCanvasRef.current) {
        previewCanvasRef.current = document.createElement("canvas");
        previewCanvasRef.current.width = TILE_SIZE;
        previewCanvasRef.current.height = TILE_SIZE;
      }
      const scratch = previewCanvasRef.current;
      const scratchCtx = scratch.getContext("2d", { willReadFrequently: true })!;
      scratchCtx.putImageData(rgbToImageData(rgb), 0, 0);

      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(scratch, screenX, screenY, width, height);
    },
    []
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

  // Set once the user pans, zooms or navigates, after which the viewport is
  // theirs and a resize must not yank it back to fit-to-screen. Explicitly
  // clicking Fit to screen deliberately does not set it.
  const hasUserAdjustedView = useRef(false);
  const markViewAdjusted = useCallback(() => {
    hasUserAdjustedView.current = true;
  }, []);

  // Keep the tile cache big enough for the current viewport. A window resized
  // larger needs proportionally more tiles at Level 2, and a cache left at the
  // old size would thrash instead of holding them.
  useEffect(() => {
    tileDataRef.current.setMaxSize(tileCacheCapacity(canvasSize.width, canvasSize.height));
  }, [canvasSize.width, canvasSize.height]);

  // Handle external navigation requests (from MiniMap)
  useEffect(() => {
    if (navigateTo) {
      markViewAdjusted();
      setOffset(navigateTo.x, navigateTo.y);
    }
  }, [navigateTo, setOffset, markViewAdjusted]);

  // Multi-level rendering state
  // Use LRU cache for chunk images to prevent unbounded memory growth
  const chunkCacheRef = useRef(new LRUCache<string, ChunkCache>(MAX_CHUNK_CACHE_SIZE));
  const loadingChunksRef = useRef<Set<string>>(new Set());
  const [chunkCacheVersion, setChunkCacheVersion] = useState(0); // Trigger re-render when chunks load

  // Determine render level based on zoom
  const screenTileSize = TILE_SIZE * zoom;
  const renderLevel = useMemo(() => getRenderLevel(screenTileSize), [screenTileSize]);

  // Level 0 image, refreshed only while it is actually the visible layer
  const mosaicOverview = useOverviewImage({
    renderLevel,
    overviewUpdate,
    onOverviewUpdateProcessed,
    onOverviewLoad,
  });

  // Create a key for the tile coordinates
  const getTileKey = (x: number, y: number) => `${x}:${y}`;

  // Calculate visible chunks for Level 1
  const getVisibleChunks = useCallback((): { cx: number; cy: number }[] => {
    if (!canvasRef.current) return [];

    // CSS pixels, deliberately: `zoom` is CSS-px-per-world-unit, so dividing a
    // device-pixel width by it would claim a viewport dpr times too wide and
    // request that many extra chunks. canvas.width is the backing store and is
    // the wrong number here.
    const canvasWidth = canvasSize.width;
    const canvasHeight = canvasSize.height;

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
  }, [offsetX, offsetY, zoom, canvasSize.width, canvasSize.height]);

  // Calculate visible tiles for Level 2
  const getVisibleTiles = useCallback((): { x: number; y: number }[] => {
    if (!canvasRef.current) return [];

    // CSS pixels — see the note in getVisibleChunks. At DPR 2 the backing-store
    // width would ask for four times the tiles, one request per tile.
    const canvasWidth = canvasSize.width;
    const canvasHeight = canvasSize.height;

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
  }, [offsetX, offsetY, zoom, canvasSize.width, canvasSize.height]);

  // Track tiles being loaded and tiles that don't exist (404)
  const loadingTilesRef = useRef<Set<string>>(new Set());
  const nonExistentTilesRef = useRef<Set<string>>(new Set());
  // Cached tiles known to be out of date: still drawn, but refetched on the
  // next loader pass.
  const staleTilesRef = useRef<Set<string>>(new Set());
  // Bumped when tiles are invalidated, to re-run the loader. Kept separate from
  // tileDataVersion, which changes on every single tile arrival and would
  // restart the loader's debounce continuously.
  const [tileInvalidation, setTileInvalidation] = useState(0);

  // The one way a tile enters the cache, used by both the loader and the
  // WebSocket/local-save path so the decode and lifecycle rules exist once.
  const storeTile = useCallback((key: string, rgb: Uint8Array) => {
    const cache = tileDataRef.current;
    const entry: TileEntry = { bitmap: null };
    // Insert synchronously: the loader treats "present" as "do not refetch",
    // and inserting only after the decode would re-request the tile on every
    // pass during the decode window.
    cache.set(key, entry);

    createImageBitmap(rgbToImageData(rgb))
      .then((bitmap) => {
        // Evicted or superseded while decoding — identity says so. Attaching
        // now would resurrect a dead entry or clobber a newer one.
        if (cache.get(key) !== entry) {
          bitmap.close();
          return;
        }
        entry.bitmap = bitmap;
        setTileDataVersion((n) => n + 1);
      })
      .catch(() => {
        // Decode failed: drop the entry so the tile can be fetched again
        // rather than sitting cached-but-blank forever.
        if (cache.get(key) === entry) cache.delete(key);
      });
  }, []);

  // Coalesced retry for tiles whose fetch failed outright. One timer for the
  // whole burst: a server hiccup fails many tiles at once and they all want the
  // same single re-run, not one apiece.
  const failedTileRetryRef = useRef<number | null>(null);
  const scheduleFailedTileRetry = useCallback(() => {
    if (failedTileRetryRef.current !== null) return;
    failedTileRetryRef.current = window.setTimeout(() => {
      failedTileRetryRef.current = null;
      setTileInvalidation((n) => n + 1);
    }, 2000);
  }, []);

  useEffect(
    () => () => {
      if (failedTileRetryRef.current !== null) clearTimeout(failedTileRetryRef.current);
    },
    []
  );

  // Animation state for selection indicator pulse
  const [selectionPulse, setSelectionPulse] = useState(0);
  const selectionAnimationRef = useRef<number | null>(null);

  // Draw the canvas with viewport transform
  const drawCanvas = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Everything below is computed in DEVICE pixels rather than CSS pixels, so
    // `s` is the scale used for drawing and `zoom` is only for CSS-space
    // reasoning (hit tests, render level, which chunks to fetch).
    //
    // The alternative — ctx.scale(dpr, dpr) and CSS-pixel math — loses on this
    // canvas specifically: every coordinate here is already Math.round()ed to
    // land on whole pixels and avoid seams, and under a scale transform those
    // rounds are whole *CSS* pixels, i.e. fractional device pixels at any
    // non-integer ratio. Rounding in device space keeps the guarantee the
    // rounding was added for. It also sidesteps ctx.scale accumulating across
    // calls and being silently reset whenever canvas.width is assigned.
    const dpr = getDevicePixelRatio();
    const width = canvas.width;
    const height = canvas.height;
    const s = zoom * dpr;

    // Clear with dark background (visible around mosaic at low zoom)
    ctx.fillStyle = "#1a1a1a";
    ctx.fillRect(0, 0, width, height);

    // Calculate mosaic position on screen
    const mosaicScreenX = (0 - offsetX) * s;
    const mosaicScreenY = (0 - offsetY) * s;
    const mosaicScreenW = MOSAIC_WIDTH * s;
    const mosaicScreenH = MOSAIC_HEIGHT * s;

    // Levels 0 and 1 draw a 2048px image scaled DOWN (a chunk spans at most
    // ~2400 CSS px on screen), where smoothing is what makes it look right.
    // Only Level 2 upscales real pixel art, and renderTileData turns smoothing
    // off for itself. This has to be set per draw: the flag used to be set
    // exclusively inside renderTileData and simply leaked onto whatever was
    // drawn next, and assigning canvas.width resets it to true anyway.
    ctx.imageSmoothingEnabled = true;

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
          const x1 = Math.round((cx * chunkWorldSize - offsetX) * s);
          const y1 = Math.round((cy * chunkWorldSize - offsetY) * s);
          const x2 = Math.round(((cx + 1) * chunkWorldSize - offsetX) * s);
          const y2 = Math.round(((cy + 1) * chunkWorldSize - offsetY) * s);
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
          const x1 = Math.round((cx * chunkWorldSize - offsetX) * s);
          const y1 = Math.round((cy * chunkWorldSize - offsetY) * s);
          const x2 = Math.round(((cx + 1) * chunkWorldSize - offsetX) * s);
          const y2 = Math.round(((cy + 1) * chunkWorldSize - offsetY) * s);
          ctx.drawImage(cached.image, x1, y1, x2 - x1, y2 - y1);
        }
      });

      // Draw loaded tile data on top (sharp tiles replace blurry chunk preview).
      // Set once for the whole batch rather than per tile: every tile is a
      // nearest-neighbour magnification of a 32px source.
      ctx.imageSmoothingEnabled = false;
      tileDataRef.current.forEach((entry, key) => {
        // Still decoding. The chunk image already covers this square, so
        // skipping is the correct fallback for the few ms it takes.
        if (!entry.bitmap) return;

        const [tileX, tileY] = key.split(":").map(Number);

        // Calculate exact pixel boundaries using rounding to avoid seams
        const x1 = Math.round((tileX * TILE_SIZE - offsetX) * s);
        const y1 = Math.round((tileY * TILE_SIZE - offsetY) * s);
        const x2 = Math.round(((tileX + 1) * TILE_SIZE - offsetX) * s);
        const y2 = Math.round(((tileY + 1) * TILE_SIZE - offsetY) * s);

        // Only draw if tile is visible in viewport
        if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
          // Height from y2 - y1, not the width: rounding can make them differ
          // by a device pixel, and reusing the width left a seam.
          ctx.drawImage(entry.bitmap, x1, y1, x2 - x1, y2 - y1);
        }
      });

      // Draw tile preview overlay (live editing preview before save)
      if (tilePreview) {
        const x1 = Math.round((tilePreview.x * TILE_SIZE - offsetX) * s);
        const y1 = Math.round((tilePreview.y * TILE_SIZE - offsetY) * s);
        const x2 = Math.round(((tilePreview.x + 1) * TILE_SIZE - offsetX) * s);
        const y2 = Math.round(((tilePreview.y + 1) * TILE_SIZE - offsetY) * s);

        // Only draw if preview tile is visible
        if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
          renderPreviewTile(ctx, x1, y1, tilePreview.pixelData, x2 - x1, y2 - y1);
        }
      }

      // Draw grid lines at Level 2 when zoomed in enough (toggleable with 'G' key)
      if (renderLevel === 2 && showGrid && screenTileSize >= GRID_THRESHOLD) {
        // Use "difference" blend mode so grid is always visible regardless of tile colors
        ctx.save();
        ctx.globalCompositeOperation = "difference";
        ctx.strokeStyle = "#ffffff"; // White + difference = inverts underlying colors
        // One CSS pixel wide. A literal 1 would now mean one *device* pixel,
        // i.e. a half-width hairline on a retina screen.
        const gridLineWidth = dpr;
        ctx.lineWidth = gridLineWidth;

        // Calculate visible tile range
        const startTileX = Math.max(0, Math.floor(offsetX / TILE_SIZE));
        const startTileY = Math.max(0, Math.floor(offsetY / TILE_SIZE));
        const endTileX = Math.min(GRID_WIDTH, Math.ceil((offsetX + width / s) / TILE_SIZE));
        const endTileY = Math.min(GRID_HEIGHT, Math.ceil((offsetY + height / s) / TILE_SIZE));

        // Draw vertical lines
        ctx.beginPath();
        for (let i = startTileX; i <= endTileX; i++) {
          // Snap to a whole device pixel, then offset by half the stroke so the
          // line covers whole pixels instead of straddling two at half opacity.
          const screenX = Math.round((i * TILE_SIZE - offsetX) * s) + gridLineWidth / 2;
          ctx.moveTo(screenX, Math.max(0, mosaicScreenY));
          ctx.lineTo(screenX, Math.min(height, mosaicScreenY + mosaicScreenH));
        }
        ctx.stroke();

        // Draw horizontal lines
        ctx.beginPath();
        for (let i = startTileY; i <= endTileY; i++) {
          const screenY = Math.round((i * TILE_SIZE - offsetY) * s) + gridLineWidth / 2;
          ctx.moveTo(Math.max(0, mosaicScreenX), screenY);
          ctx.lineTo(Math.min(width, mosaicScreenX + mosaicScreenW), screenY);
        }
        ctx.stroke();
        ctx.restore();
      }
    }

    // Draw selection indicator for selected tile (on all levels, after everything else)
    const tileToHighlight =
      selectedTile || (tilePreview ? { x: tilePreview.x, y: tilePreview.y } : null);
    if (tileToHighlight) {
      const x1 = Math.round((tileToHighlight.x * TILE_SIZE - offsetX) * s);
      const y1 = Math.round((tileToHighlight.y * TILE_SIZE - offsetY) * s);
      const x2 = Math.round(((tileToHighlight.x + 1) * TILE_SIZE - offsetX) * s);
      const y2 = Math.round(((tileToHighlight.y + 1) * TILE_SIZE - offsetY) * s);
      const tileW = x2 - x1;
      const tileH = y2 - y1;

      // Only draw if tile is visible
      if (x2 > 0 && x1 < width && y2 > 0 && y1 < height) {
        // Pulsing black border (opacity varies from 0.2 to 1.0)
        const opacity = 0.2 + selectionPulse * 0.8;
        ctx.strokeStyle = `rgba(0, 0, 0, ${opacity})`;
        ctx.lineWidth = 3 * dpr; // 3 CSS pixels
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
    renderPreviewTile,
    showGrid,
    tilePreview,
    selectedTile,
    selectionPulse,
    // Assigning canvas.width on resize *clears* the surface, so a resize must
    // always schedule a repaint. Nothing else here changes when only the size
    // does: the viewport is untouched once hasUserAdjustedView gates off the
    // re-fit, and getVisibleChunks keys on offset/zoom. Without these two the
    // canvas stayed blank after any resize that followed a pan, until some
    // unrelated state happened to redraw it.
    canvasSize.width,
    canvasSize.height,
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

  // Process tile updates (from WebSocket or local saves) - Level 2 pixel data only
  useEffect(() => {
    if (!tileUpdate) return;

    const key = getTileKey(tileUpdate.x, tileUpdate.y);

    // Clear non-existent flag in case tile was previously 404
    nonExistentTilesRef.current.delete(key);

    // Handle tile pixel data for Level 2 (instant, no need to wait for backend)
    if (tileUpdate.pixelData) {
      storeTile(key, tileUpdate.pixelData!);
      setTileDataVersion((n) => n + 1); // Trigger re-render
      onTileUpdateProcessed?.();
    }
    // Chunk and overview updates are handled separately via WebSocket messages
  }, [tileUpdate, onTileUpdateProcessed, storeTile]);

  // Process chunk updates (from WebSocket) - Level 1 chunk images
  useEffect(() => {
    if (!chunkUpdate) return;

    const { cx, cy, version } = chunkUpdate;
    const chunkKey = `${cx}_${cy}`;

    // Mark this chunk's Level-2 tiles for revalidation. A tile is otherwise
    // fetched once and only ever overwritten by a tile_update echo, and sharp
    // tiles are drawn on top of the chunk image — so one missed echo left
    // another user's pre-edit pixels on screen indefinitely, with the chunk's
    // own self-heal masked underneath.
    //
    // Marked, not evicted: the cached pixels keep drawing until the refetch
    // lands. Dropping them would fall back to the upscaled chunk image and blur
    // every tile in view for a moment after each edit — including the editor's
    // own, immediately after they saved it.
    const inThisChunk = (key: string): boolean => {
      const [tileX, tileY] = key.split(":").map(Number);
      return Math.floor(tileX / CHUNK_SIZE) === cx && Math.floor(tileY / CHUNK_SIZE) === cy;
    };

    let invalidated = 0;
    tileDataRef.current.forEach((_rgb, key) => {
      if (inThisChunk(key)) {
        staleTilesRef.current.add(key);
        invalidated++;
      }
    });

    // A tile created since we last looked would still be flagged 404 here.
    // Nothing is cached for those, so clearing the flag is free.
    for (const key of nonExistentTilesRef.current) {
      if (inThisChunk(key)) {
        nonExistentTilesRef.current.delete(key);
        invalidated++;
      }
    }

    if (invalidated > 0) {
      setTileInvalidation((n) => n + 1); // Re-run the tile loader
    }

    // Load the updated chunk image
    const loadUpdatedChunk = async () => {
      try {
        const img = await loadChunkImage(cx, cy, version);
        chunkCacheRef.current.set(chunkKey, { image: img, version });
        setChunkCacheVersion((n) => n + 1);
        console.log(`Chunk (${cx}, ${cy}) reloaded with version ${version}`);
      } catch (error) {
        console.error(`Failed to reload chunk ${chunkKey}:`, error);
      } finally {
        onChunkUpdateProcessed?.();
      }
    };
    loadUpdatedChunk();
  }, [chunkUpdate, onChunkUpdateProcessed]);

  // Track if canvas has been initialized
  const [isCanvasReady, setIsCanvasReady] = useState(false);

  // RAF batching - prevent multiple drawCanvas calls per frame
  const rafIdRef = useRef<number | null>(null);
  const pendingDrawRef = useRef(false);

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

      const stale = staleTilesRef.current;

      sortedTiles.forEach(({ x, y }) => {
        const key = getTileKey(x, y);
        // Skip if already loading, or already loaded and still believed current.
        //
        // get() rather than has(): get() is the only method that refreshes LRU
        // recency, and nothing else calls it on this cache, so eviction order
        // was really insertion order. Combined with the centre-first sort just
        // above, that made the cache evict the middle of the screen first —
        // exactly backwards. Touching each visible tile here keys recency to
        // visibility, which is what the eviction policy should follow.
        if (loading.has(key)) return;
        if (!stale.has(key) && (tileCache.get(key) !== undefined || nonExistent.has(key))) return;

        loading.add(key);
        stale.delete(key);

        tileLoader
          .loadTile(x, y)
          .then((result) => {
            loading.delete(key);

            if (result === TILE_CANCELLED) {
              // Cancelled (e.g. during panning). Restore the revalidation mark,
              // or a stale tile would never be refetched.
              if (tileCache.has(key)) stale.add(key);
              return;
            }

            if (result === null) {
              // Tile doesn't exist (404) - mark as non-existent
              nonExistent.add(key);
              // It may have existed a moment ago; don't keep drawing a tile the
              // server has since reset.
              if (tileCache.delete(key)) {
                setTileDataVersion((n) => n + 1);
              }
              return;
            }

            // Got valid tile data - decode it into the cache. storeTile bumps
            // tileDataVersion itself once the bitmap is ready to draw.
            storeTile(key, result);
          })
          .catch(() => {
            loading.delete(key);
            if (tileCache.has(key)) stale.add(key);
            // ...and actually retry, which the comment here used to claim
            // without doing. A tile that has never loaded ends up in no set at
            // all — not cached, not loading, not stale, not non-existent — and
            // this effect only re-runs when the viewport changes, so a single
            // transient failure left a permanent hole until the user panned.
            // Nudging tileInvalidation re-runs the pass, which re-enqueues it.
            scheduleFailedTileRetry();
          });
      });
    }, 50); // 50ms debounce

    return () => clearTimeout(timeoutId);
  }, [
    renderLevel,
    getVisibleTiles,
    // tileDataVersion not needed - we check the ref directly
    tileInvalidation, // but a chunk update marks tiles stale, which must refetch
    storeTile, // stable; decodes an arriving tile into the cache
    scheduleFailedTileRetry, // stable; bumps tileInvalidation after a failure
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

      const cssWidth = window.innerWidth;
      const cssHeight = window.innerHeight;
      const dpr = getDevicePixelRatio();

      // Backing store in device pixels...
      canvas.width = Math.round(cssWidth * dpr);
      canvas.height = Math.round(cssHeight * dpr);
      // ...and an explicit CSS size, which the element does not otherwise have:
      // App.css only sets `canvas { display: block }`, so layout size comes from
      // these attributes. Without the two lines below a DPR-2 device would lay
      // the canvas out at twice the viewport width.
      canvas.style.width = `${cssWidth}px`;
      canvas.style.height = `${cssHeight}px`;

      // Kept in CSS pixels: this feeds useViewport, whose zoom, clamping and
      // fit-to-screen are all CSS-space, and the two visible-range helpers.
      setCanvasSize({ width: cssWidth, height: cssHeight });
      setIsCanvasReady(true);
    };

    // Initial setup
    handleResize();

    window.addEventListener("resize", handleResize);

    // devicePixelRatio changes when the window moves to a display of a
    // different density, and when the browser is zoomed. Neither reliably
    // fires `resize`, and the query has to be re-armed after every change
    // because it is pinned to the ratio that was current when it was created.
    let dprQuery: MediaQueryList | null = null;
    const handleDprChange = () => {
      handleResize();
      armDprQuery();
    };
    function armDprQuery() {
      dprQuery?.removeEventListener("change", handleDprChange);
      dprQuery = window.matchMedia(`(resolution: ${window.devicePixelRatio}dppx)`);
      dprQuery.addEventListener("change", handleDprChange);
    }
    armDprQuery();

    return () => {
      window.removeEventListener("resize", handleResize);
      dprQuery?.removeEventListener("change", handleDprChange);
    };
  }, []);

  // Keep the mosaic fitted to the canvas until the user takes control.
  //
  // This used to run exactly once, against whatever size the canvas happened to
  // measure first. Any window that settled a moment after load — a preview
  // pane, a restored window, a phone rotating — left the mosaic stuck at that
  // first tiny zoom, and the only way out was finding the Fit to screen button.
  // resetView's identity changes with the canvas size, so this re-fits on every
  // resize until a pan or zoom sets hasUserAdjustedView.
  useEffect(() => {
    if (!isCanvasReady) return;
    if (hasUserAdjustedView.current) return;
    resetView();
  }, [isCanvasReady, resetView]);

  // Always paint the newest state, not whichever one first asked for a frame.
  //
  // The pending frame used to hold the drawCanvas captured when it was
  // scheduled, and every later request returned early without re-arming — so
  // any state that changed before the frame ran was drawn stale, and never
  // redrawn afterwards. Tiles arrive in bursts of MAX_CONCURRENT per round
  // trip and each one bumps a version counter, so most of a Level 2 fill was
  // being dropped this way. Reading the latest drawCanvas out of a ref at
  // frame time keeps the coalescing while always drawing current state.
  const drawCanvasRef = useRef(drawCanvas);
  useEffect(() => {
    drawCanvasRef.current = drawCanvas;
  }, [drawCanvas]);

  const scheduleRedraw = useCallback(() => {
    if (pendingDrawRef.current) return; // A frame is already coming

    pendingDrawRef.current = true;
    rafIdRef.current = requestAnimationFrame(() => {
      pendingDrawRef.current = false;
      rafIdRef.current = null;
      drawCanvasRef.current();
    });
  }, []);

  // Cleanup RAF on unmount
  useEffect(() => {
    return () => {
      if (rafIdRef.current !== null) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, []);

  // Redraw canvas when dependencies change (only after canvas is ready).
  // Uses RAF batching to prevent multiple redraws per frame.
  //
  // `drawCanvas` is the dependency that matters: its identity changes whenever
  // anything it paints changes, and that is what asks for the next frame.
  // scheduleRedraw is stable now, so depending on it alone would run this once
  // and never repaint again.
  useEffect(() => {
    if (isCanvasReady) {
      scheduleRedraw();
    }
  }, [isCanvasReady, scheduleRedraw, drawCanvas]);

  // Global mouse handlers during drag
  useEffect(() => {
    if (!isDragging) return;

    const handleMouseMove = (e: MouseEvent) => {
      const deltaX = e.clientX - lastMousePos.current.x;
      const deltaY = e.clientY - lastMousePos.current.y;
      lastMousePos.current = { x: e.clientX, y: e.clientY };
      markViewAdjusted();
      pan(deltaX, deltaY);
    };

    const handleMouseUp = () => setIsDragging(false);

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, pan, markViewAdjusted]);

  // Wheel handler for zooming/panning (native event for passive: false)
  // Intent classification lives in utils/wheel.ts — see the note there on why
  // deltaMode alone cannot separate a mouse wheel from a trackpad swipe.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      markViewAdjusted();

      const intent = classifyWheel(e as WheelLike);

      if (intent === "zoom") {
        const rect = canvas.getBoundingClientRect();
        const canvasX = e.clientX - rect.left;
        const canvasY = e.clientY - rect.top;
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        zoomAt(canvasX, canvasY, factor);
      } else {
        // Trackpad 2-finger swipe.
        // pan() already converts screen pixels to world coordinates.
        pan(-e.deltaX, -e.deltaY);
      }
    };

    canvas.addEventListener("wheel", handleWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", handleWheel);
  }, [zoomAt, pan, markViewAdjusted]);

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

  // Zoom from the on-screen controls is a deliberate viewport choice; Fit to
  // screen is not, so it keeps calling resetView directly.
  const handleZoomChange = useCallback(
    (newZoom: number) => {
      markViewAdjusted();
      setZoom(newZoom);
    },
    [setZoom, markViewAdjusted]
  );

  // Mouse down handler for drag start
  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    lastMousePos.current = { x: e.clientX, y: e.clientY };
    dragStartPos.current = { x: e.clientX, y: e.clientY };
  };

  // The one screen -> tile mapping. Kept in one place because the touch
  // handlers need exactly this and would otherwise copy it.
  //
  // Entirely CSS-space: getBoundingClientRect and pointer coordinates are both
  // CSS pixels, and `zoom` is CSS-px-per-world-unit, so the device pixel ratio
  // must NOT appear here. It belongs only to the draw path.
  //
  // Returns null when the point is outside the mosaic.
  const screenToTile = useCallback(
    (clientX: number, clientY: number): TileCoordinates | null => {
      const canvas = canvasRef.current;
      if (!canvas) return null;

      const rect = canvas.getBoundingClientRect();
      const worldX = (clientX - rect.left) / zoom + offsetX;
      const worldY = (clientY - rect.top) / zoom + offsetY;

      if (worldX < 0 || worldX >= MOSAIC_WIDTH || worldY < 0 || worldY >= MOSAIC_HEIGHT) {
        return null;
      }

      const tileX = Math.floor(worldX / TILE_SIZE);
      const tileY = Math.floor(worldY / TILE_SIZE);
      if (tileX < 0 || tileX >= GRID_WIDTH || tileY < 0 || tileY >= GRID_HEIGHT) {
        return null;
      }
      return { x: tileX, y: tileY };
    },
    [zoom, offsetX, offsetY]
  );

  // What a tap or click means depends on how far in you are.
  //
  // Below Level 2 a tile is under 24 px and, at Level 0, under 3 px — smaller
  // than a fingertip and smaller than a cursor hotspot. Opening a full-screen
  // editor on whichever tile happened to be under the point is a hostile
  // outcome, so the action is gated on zoom instead. The gate applies to the
  // mouse as well as touch: the same 3 px target is just as unaimable with a
  // cursor, and leaving click-to-edit on at Level 0 would keep exactly the
  // behaviour this exists to remove.
  const canEditAtThisZoom = renderLevel === 2;

  const handleTap = useCallback(
    (clientX: number, clientY: number) => {
      if (!canEditAtThisZoom) return;
      const tile = screenToTile(clientX, clientY);
      if (tile) onTileClick?.(tile);
    },
    [canEditAtThisZoom, screenToTile, onTileClick]
  );

  // Zoom toward the point, the way double-tap works on a map.
  //
  // Bound to the double rather than the single tap because a single tap that
  // moves the view leaves no way to just look at the mosaic — and by the 10 px
  // touch threshold a slightly nudged pan already counts as a tap. Pairing it
  // with "single tap does nothing below Level 2" also means the double-tap
  // window costs no latency: there is no single-tap action to delay, and at
  // Level 2, where there is one, it fires immediately.
  const handleDoubleTap = useCallback(
    (clientX: number, clientY: number) => {
      if (canEditAtThisZoom) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      markViewAdjusted();
      zoomAt(clientX - rect.left, clientY - rect.top, DOUBLE_TAP_ZOOM_FACTOR);
    },
    [canEditAtThisZoom, zoomAt, markViewAdjusted]
  );

  useCanvasGestures(canvasRef, {
    pan,
    zoomAt,
    onTap: handleTap,
    onDoubleTap: handleDoubleTap,
    onViewportGesture: markViewAdjusted,
  });

  // Click handler - distinguish from drag
  const handleClick = (e: React.MouseEvent) => {
    // Only trigger click if mouse didn't move much (not a drag)
    const dx = e.clientX - dragStartPos.current.x;
    const dy = e.clientY - dragStartPos.current.y;
    if (Math.abs(dx) > 5 || Math.abs(dy) > 5) return;

    handleTap(e.clientX, e.clientY);
  };

  const handleDoubleClick = (e: React.MouseEvent) => {
    handleDoubleTap(e.clientX, e.clientY);
  };

  return (
    <>
      <canvas
        ref={canvasRef}
        className="mosaic-canvas"
        onMouseDown={handleMouseDown}
        onClick={handleClick}
        onDoubleClick={handleDoubleClick}
        style={{ cursor: isDragging ? "grabbing" : "grab" }}
        role="application"
        aria-label="Mosaic editor canvas"
      />
      <ZoomControls
        zoom={zoom}
        minZoom={minZoom}
        maxZoom={maxZoom}
        onZoomChange={handleZoomChange}
        onReset={resetView}
        showGrid={showGrid}
        onToggleGrid={() => setShowGrid((prev) => !prev)}
      />
    </>
  );
}
