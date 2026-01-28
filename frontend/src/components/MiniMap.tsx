import { useRef, useEffect, useState, useCallback, useMemo } from "react";
import { Map, ChevronDown } from "lucide-react";
import { MOSAIC_CONFIG } from "../config";
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
}

export function MiniMap({
  overviewImage,
  viewportX,
  viewportY,
  viewportZoom,
  canvasWidth,
  canvasHeight,
  onNavigate,
}: MiniMapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

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

    // Draw if we have a cached overview
    const cachedOverview = cachedOverviewRef.current;
    if (!cachedOverview) return;

    // Draw cached overview (fast blit)
    ctx.drawImage(cachedOverview, 0, 0);

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
  }, [overviewImage, rectX, rectY, rectW, rectH, collapsed]);

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

  if (collapsed) {
    return (
      <button
        className="minimap minimap--collapsed glass-panel"
        onClick={() => setCollapsed(false)}
        title="Show map"
      >
        <Map size={18} />
      </button>
    );
  }

  return (
    <div className="minimap glass-panel">
      <div className="minimap__header">
        <span className="minimap__title">Map</span>
        <button className="minimap__toggle" onClick={() => setCollapsed(true)} title="Hide map">
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
    </div>
  );
}
