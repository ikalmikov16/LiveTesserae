import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { Map, ChevronDown, Search } from "lucide-react";
import { MOSAIC_CONFIG } from "../config";
import type { TileCoordinates } from "../types";
import "./MiniMap.css";

const { GRID_WIDTH, TILE_SIZE } = MOSAIC_CONFIG;
const MOSAIC_WIDTH = GRID_WIDTH * TILE_SIZE;
const MINIMAP_SIZE = 150;

interface MiniMapProps {
  overviewImage: HTMLImageElement | null;
  viewportX: number;
  viewportY: number;
  viewportZoom: number;
  canvasWidth: number;
  canvasHeight: number;
  onNavigate: (x: number, y: number) => void;
  editingTile?: TileCoordinates | null;
  onGoToTile?: (x: number, y: number) => void;
}

export function MiniMap({
  overviewImage,
  viewportX,
  viewportY,
  viewportZoom,
  canvasWidth,
  canvasHeight,
  onNavigate,
  editingTile,
  onGoToTile,
}: MiniMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [gotoX, setGotoX] = useState("");
  const [gotoY, setGotoY] = useState("");

  // Cached overview canvas (only redrawn when image changes)
  const cachedOverviewRef = useRef<HTMLCanvasElement | null>(null);
  // Track which image src we've cached
  const cachedImageSrcRef = useRef<string | null>(null);

  // Scale factor: minimap pixels per world pixel
  const scale = MINIMAP_SIZE / MOSAIC_WIDTH;

  // Viewport rectangle in minimap coordinates (memoized to prevent unnecessary recalculations)
  const viewport = useMemo(() => {
    const viewportWidth = canvasWidth / viewportZoom;
    const viewportHeight = canvasHeight / viewportZoom;
    return {
      width: viewportWidth,
      height: viewportHeight,
      rectX: viewportX * scale,
      rectY: viewportY * scale,
      rectW: viewportWidth * scale,
      rectH: viewportHeight * scale,
    };
  }, [canvasWidth, canvasHeight, viewportZoom, viewportX, viewportY, scale]);

  const { rectX, rectY, rectW, rectH } = viewport;

  // Calculate editing tile position on minimap
  const editingTilePos = useMemo(() => {
    if (!editingTile) return null;
    // Center of the tile in world coordinates, then scaled to minimap
    const worldX = (editingTile.x + 0.5) * TILE_SIZE;
    const worldY = (editingTile.y + 0.5) * TILE_SIZE;
    return {
      x: worldX * scale,
      y: worldY * scale,
    };
  }, [editingTile, scale]);

  // Cache and draw minimap in a single effect
  // This avoids the need for state to track "readiness"
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || collapsed) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Update cache if image changed
    if (overviewImage) {
      if (cachedImageSrcRef.current !== overviewImage.src) {
        // Create offscreen canvas for cached overview
        const offscreen = document.createElement("canvas");
        offscreen.width = MINIMAP_SIZE;
        offscreen.height = MINIMAP_SIZE;
        const offCtx = offscreen.getContext("2d");
        if (offCtx) {
          offCtx.drawImage(overviewImage, 0, 0, MINIMAP_SIZE, MINIMAP_SIZE);
        }
        cachedOverviewRef.current = offscreen;
        cachedImageSrcRef.current = overviewImage.src;
      }
    } else {
      cachedOverviewRef.current = null;
      cachedImageSrcRef.current = null;
    }

    // Clear canvas first
    ctx.fillStyle = "#1a1a1a";
    ctx.fillRect(0, 0, MINIMAP_SIZE, MINIMAP_SIZE);

    // Draw cached overview if available
    const cachedOverview = cachedOverviewRef.current;
    if (cachedOverview) {
      ctx.drawImage(cachedOverview, 0, 0);
    }

    // Draw viewport rectangle with semi-transparent fill
    ctx.fillStyle = "rgba(255, 255, 255, 0.15)";
    ctx.fillRect(rectX, rectY, rectW, rectH);

    // Draw double-stroke for visibility against any background:
    // 1. Outer white stroke (wider)
    ctx.strokeStyle = "rgba(255, 255, 255, 0.9)";
    ctx.lineWidth = 3;
    ctx.strokeRect(rectX, rectY, rectW, rectH);

    // 2. Inner dark stroke (narrower)
    ctx.strokeStyle = "rgba(0, 0, 0, 0.7)";
    ctx.lineWidth = 1;
    ctx.strokeRect(rectX, rectY, rectW, rectH);

    // Draw crosshairs for editing tile (LAST so they're on top of everything)
    if (editingTilePos) {
      ctx.strokeStyle = "#ff3366";
      ctx.lineWidth = 1;

      // Vertical line
      ctx.beginPath();
      ctx.moveTo(editingTilePos.x, 0);
      ctx.lineTo(editingTilePos.x, MINIMAP_SIZE);
      ctx.stroke();

      // Horizontal line
      ctx.beginPath();
      ctx.moveTo(0, editingTilePos.y);
      ctx.lineTo(MINIMAP_SIZE, editingTilePos.y);
      ctx.stroke();

      // Draw small marker at tile position
      ctx.fillStyle = "#ff3366";
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(editingTilePos.x, editingTilePos.y, 3, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }, [overviewImage, rectX, rectY, rectW, rectH, collapsed, editingTilePos]);

  // Convert minimap coordinates to world coordinates and navigate
  const navigateToPoint = useCallback(
    (minimapX: number, minimapY: number) => {
      // Convert minimap coords to world coords
      const worldX = minimapX / scale;
      const worldY = minimapY / scale;
      // Center viewport on clicked point
      const newOffsetX = worldX - viewport.width / 2;
      const newOffsetY = worldY - viewport.height / 2;
      onNavigate(newOffsetX, newOffsetY);
    },
    [scale, viewport.width, viewport.height, onNavigate]
  );

  // Handle click to navigate
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (isDragging) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const minimapX = e.clientX - rect.left;
      const minimapY = e.clientY - rect.top;
      navigateToPoint(minimapX, minimapY);
    },
    [isDragging, navigateToPoint]
  );

  // Handle drag to pan viewport
  const handleMouseDown = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const minimapX = e.clientX - rect.left;
      const minimapY = e.clientY - rect.top;

      // Check if click is inside viewport rectangle
      if (
        minimapX >= rectX &&
        minimapX <= rectX + rectW &&
        minimapY >= rectY &&
        minimapY <= rectY + rectH
      ) {
        setIsDragging(true);
        e.preventDefault();
      }
    },
    [rectX, rectY, rectW, rectH]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!isDragging) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const minimapX = e.clientX - rect.left;
      const minimapY = e.clientY - rect.top;
      navigateToPoint(minimapX, minimapY);
    },
    [isDragging, navigateToPoint]
  );

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
  }, []);

  // Global mouse up listener for drag release outside canvas
  useEffect(() => {
    if (!isDragging) return;

    const handleGlobalMouseUp = () => setIsDragging(false);
    window.addEventListener("mouseup", handleGlobalMouseUp);
    return () => window.removeEventListener("mouseup", handleGlobalMouseUp);
  }, [isDragging]);

  // Handle Go to X,Y submission
  const handleGoTo = useCallback(
    (e?: React.FormEvent) => {
      e?.preventDefault();
      const x = parseInt(gotoX, 10);
      const y = parseInt(gotoY, 10);

      // Validate coordinates
      if (isNaN(x) || isNaN(y) || x < 0 || x >= GRID_WIDTH || y < 0 || y >= GRID_WIDTH) {
        return;
      }

      // Navigate to center the tile on screen
      const worldX = (x + 0.5) * TILE_SIZE - viewport.width / 2;
      const worldY = (y + 0.5) * TILE_SIZE - viewport.height / 2;
      onNavigate(worldX, worldY);

      // Also trigger tile selection if callback provided
      onGoToTile?.(x, y);

      // Clear inputs
      setGotoX("");
      setGotoY("");
    },
    [gotoX, gotoY, viewport.width, viewport.height, onNavigate, onGoToTile]
  );

  if (collapsed) {
    return (
      <button
        className="minimap minimap--collapsed glass-panel"
        onClick={() => setCollapsed(false)}
        title="Show map"
        aria-label="Show map"
      >
        <Map size={18} />
      </button>
    );
  }

  return (
    <div className="minimap glass-panel">
      <div className="minimap__header">
        <span className="minimap__title">Map</span>
        <button
          className="minimap__toggle"
          onClick={() => setCollapsed(true)}
          title="Hide map"
          aria-label="Hide map"
        >
          <ChevronDown size={16} />
        </button>
      </div>
      <canvas
        ref={canvasRef}
        className="minimap__canvas"
        width={MINIMAP_SIZE}
        height={MINIMAP_SIZE}
        onClick={handleClick}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: isDragging ? "grabbing" : "crosshair" }}
      />
      <form className="minimap__goto" onSubmit={handleGoTo}>
        <input
          type="text"
          className="minimap__goto-input"
          placeholder="X"
          value={gotoX}
          onChange={(e) => {
            const val = e.target.value.replace(/\D/g, "");
            // Limit to 999
            const num = parseInt(val, 10);
            if (val === "" || (num >= 0 && num <= 999)) {
              setGotoX(val);
            }
          }}
          maxLength={3}
        />
        <span className="minimap__goto-sep">,</span>
        <input
          type="text"
          className="minimap__goto-input"
          placeholder="Y"
          value={gotoY}
          onChange={(e) => {
            const val = e.target.value.replace(/\D/g, "");
            // Limit to 999
            const num = parseInt(val, 10);
            if (val === "" || (num >= 0 && num <= 999)) {
              setGotoY(val);
            }
          }}
          maxLength={3}
        />
        <button
          type="submit"
          className="minimap__goto-btn"
          title="Go to tile"
          aria-label="Go to tile"
        >
          <Search size={14} />
        </button>
      </form>
    </div>
  );
}
