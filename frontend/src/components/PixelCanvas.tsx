import { useRef, useEffect, useCallback, useState } from "react";
import { usePixelCanvas } from "../hooks/usePixelCanvas";
import type { Tool } from "./Toolbar";
import "./PixelCanvas.css";

const PIXEL_SIZE = 9; // Display scale factor (288px for 32px tile)

interface PixelCanvasProps {
  color: string;
  tool?: Tool;
  showGrid?: boolean;
  onColorPick?: (color: string) => void;
  onChange?: () => void;
  onCanvasReady: (helpers: {
    clear: () => void;
    fill: (color: string) => void;
    getCanvas: () => HTMLCanvasElement;
    loadFromImage: (img: HTMLImageElement) => void;
    setShowGrid: (show: boolean) => void;
    undo: () => boolean;
    redo: () => boolean;
    canUndo: boolean;
    canRedo: boolean;
  }) => void;
}

export function PixelCanvas({
  color,
  tool = "pencil",
  showGrid: showGridProp = true,
  onColorPick,
  onChange,
  onCanvasReady,
}: PixelCanvasProps) {
  const displayCanvasRef = useRef<HTMLCanvasElement>(null);
  const {
    setPixel,
    getPixel,
    clear,
    fill,
    floodFill,
    getCanvas,
    loadFromImage,
    beginDrawing,
    undo,
    redo,
    canUndo,
    canRedo,
    canvasSize,
  } = usePixelCanvas();
  const [isDrawing, setIsDrawing] = useState(false);
  const [showGrid, setShowGrid] = useState(showGridProp);
  const [hoverPixel, setHoverPixel] = useState<{ x: number; y: number } | null>(null);
  const hasStartedDrawingRef = useRef(false);

  const displaySize = canvasSize * PIXEL_SIZE; // 288px

  // Sync showGrid with prop changes
  useEffect(() => {
    setShowGrid(showGridProp);
  }, [showGridProp]);

  // Render the pixel data to the display canvas
  const renderDisplay = useCallback(() => {
    const displayCanvas = displayCanvasRef.current;
    if (!displayCanvas) return;

    const ctx = displayCanvas.getContext("2d");
    if (!ctx) return;

    const pixelCanvas = getCanvas();

    // Disable image smoothing for crisp pixels
    ctx.imageSmoothingEnabled = false;

    // Draw the pixel canvas scaled up
    ctx.drawImage(pixelCanvas, 0, 0, displaySize, displaySize);

    // Draw grid overlay if enabled
    if (showGrid) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.15)";
      ctx.lineWidth = 1;

      for (let i = 0; i <= canvasSize; i++) {
        const pos = i * PIXEL_SIZE;
        ctx.beginPath();
        ctx.moveTo(pos + 0.5, 0);
        ctx.lineTo(pos + 0.5, displaySize);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(0, pos + 0.5);
        ctx.lineTo(displaySize, pos + 0.5);
        ctx.stroke();
      }
    }

    // Draw hover highlight
    if (hoverPixel) {
      ctx.strokeStyle = "rgba(74, 158, 255, 0.8)";
      ctx.lineWidth = 2;
      ctx.strokeRect(
        hoverPixel.x * PIXEL_SIZE + 1,
        hoverPixel.y * PIXEL_SIZE + 1,
        PIXEL_SIZE - 2,
        PIXEL_SIZE - 2
      );
    }
  }, [getCanvas, displaySize, canvasSize, showGrid, hoverPixel]);

  // Wrap undo/redo to also re-render
  const handleUndo = useCallback(() => {
    const result = undo();
    if (result) renderDisplay();
    return result;
  }, [undo, renderDisplay]);

  const handleRedo = useCallback(() => {
    const result = redo();
    if (result) renderDisplay();
    return result;
  }, [redo, renderDisplay]);

  // Expose helpers to parent
  useEffect(() => {
    onCanvasReady({
      clear: () => {
        clear();
        renderDisplay();
      },
      fill: (fillColor: string) => {
        fill(fillColor);
        renderDisplay();
      },
      getCanvas,
      loadFromImage: (img: HTMLImageElement) => {
        loadFromImage(img);
        renderDisplay();
      },
      setShowGrid: (show: boolean) => {
        setShowGrid(show);
      },
      undo: handleUndo,
      redo: handleRedo,
      canUndo,
      canRedo,
    });
  }, [
    clear,
    fill,
    getCanvas,
    loadFromImage,
    onCanvasReady,
    renderDisplay,
    handleUndo,
    handleRedo,
    canUndo,
    canRedo,
  ]);

  // Initial render
  useEffect(() => {
    renderDisplay();
  }, [renderDisplay]);

  // Convert mouse position to pixel coordinates
  const getPixelCoords = (e: React.MouseEvent | React.TouchEvent) => {
    const canvas = displayCanvasRef.current;
    if (!canvas) return null;

    const rect = canvas.getBoundingClientRect();
    let clientX: number, clientY: number;

    if ("touches" in e) {
      if (e.touches.length === 0) return null;
      clientX = e.touches[0].clientX;
      clientY = e.touches[0].clientY;
    } else {
      clientX = e.clientX;
      clientY = e.clientY;
    }

    const x = Math.floor((clientX - rect.left) / PIXEL_SIZE);
    const y = Math.floor((clientY - rect.top) / PIXEL_SIZE);

    if (x < 0 || x >= canvasSize || y < 0 || y >= canvasSize) {
      return null;
    }

    return { x, y };
  };

  // Handle tool action at coordinates
  const handleToolAction = (x: number, y: number, isStart: boolean) => {
    switch (tool) {
      case "pencil":
        if (isStart && !hasStartedDrawingRef.current) {
          beginDrawing();
          hasStartedDrawingRef.current = true;
          onChange?.();
        }
        setPixel(x, y, color);
        renderDisplay();
        break;
      case "eraser":
        if (isStart && !hasStartedDrawingRef.current) {
          beginDrawing();
          hasStartedDrawingRef.current = true;
          onChange?.();
        }
        setPixel(x, y, "#ffffff");
        renderDisplay();
        break;
      case "fill":
        if (isStart) {
          floodFill(x, y, color);
          renderDisplay();
          onChange?.();
        }
        break;
      case "eyedropper":
        if (isStart) {
          const pickedColor = getPixel(x, y);
          onColorPick?.(pickedColor);
        }
        break;
    }
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDrawing(true);
    hasStartedDrawingRef.current = false;
    const coords = getPixelCoords(e);
    if (coords) {
      handleToolAction(coords.x, coords.y, true);
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    const coords = getPixelCoords(e);

    // Update hover highlight
    if (coords) {
      if (hoverPixel?.x !== coords.x || hoverPixel?.y !== coords.y) {
        setHoverPixel(coords);
      }
    } else {
      setHoverPixel(null);
    }

    // Draw if mouse is down (for pencil/eraser)
    if (isDrawing && coords && (tool === "pencil" || tool === "eraser")) {
      handleToolAction(coords.x, coords.y, false);
    }
  };

  const handleMouseUp = useCallback(() => {
    setIsDrawing(false);
    hasStartedDrawingRef.current = false;
  }, []);

  const handleMouseLeave = () => {
    // Don't reset isDrawing on leave - let window mouseup handle it
    // This prevents issues when dragging outside the canvas
    setHoverPixel(null);
  };

  // Global mouseup handler to ensure drawing stops even when released outside canvas
  useEffect(() => {
    if (!isDrawing) return;

    const handleGlobalMouseUp = () => {
      setIsDrawing(false);
      hasStartedDrawingRef.current = false;
    };

    window.addEventListener("mouseup", handleGlobalMouseUp);
    return () => window.removeEventListener("mouseup", handleGlobalMouseUp);
  }, [isDrawing]);

  // Touch handlers
  const handleTouchStart = (e: React.TouchEvent) => {
    e.preventDefault();
    setIsDrawing(true);
    hasStartedDrawingRef.current = false;
    const coords = getPixelCoords(e);
    if (coords) {
      handleToolAction(coords.x, coords.y, true);
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    e.preventDefault();
    if (!isDrawing) return;
    const coords = getPixelCoords(e);
    if (coords && (tool === "pencil" || tool === "eraser")) {
      handleToolAction(coords.x, coords.y, false);
    }
  };

  const handleTouchEnd = () => {
    setIsDrawing(false);
    hasStartedDrawingRef.current = false;
  };

  // Get cursor style based on tool
  const getCursorStyle = () => {
    switch (tool) {
      case "eyedropper":
        return "crosshair";
      case "fill":
        return "cell";
      default:
        return "crosshair";
    }
  };

  return (
    <div className="pixel-canvas-container">
      <canvas
        ref={displayCanvasRef}
        width={displaySize}
        height={displaySize}
        className="pixel-canvas"
        style={{ cursor: getCursorStyle() }}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      />
    </div>
  );
}
