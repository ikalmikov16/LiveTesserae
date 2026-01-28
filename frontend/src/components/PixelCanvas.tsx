import { useRef, useEffect, useCallback, useState } from "react";
import { usePixelCanvas } from "../hooks/usePixelCanvas";
import "./PixelCanvas.css";

const PIXEL_SIZE = 10; // Display scale factor

interface PixelCanvasProps {
  color: string;
  onCanvasReady: (helpers: {
    clear: () => void;
    fill: (color: string) => void;
    getCanvas: () => HTMLCanvasElement;
    loadFromImage: (img: HTMLImageElement) => void;
  }) => void;
}

export function PixelCanvas({ color, onCanvasReady }: PixelCanvasProps) {
  const displayCanvasRef = useRef<HTMLCanvasElement>(null);
  const { setPixel, clear, fill, getCanvas, loadFromImage, canvasSize } = usePixelCanvas();
  const [isDrawing, setIsDrawing] = useState(false);
  const [showGrid, setShowGrid] = useState(true);

  const displaySize = canvasSize * PIXEL_SIZE; // 320px

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
      ctx.strokeStyle = "rgba(0, 0, 0, 0.1)";
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
  }, [getCanvas, displaySize, canvasSize, showGrid]);

  // Expose helpers to parent
  useEffect(() => {
    onCanvasReady({
      clear: () => {
        clear();
        renderDisplay();
      },
      fill: (color: string) => {
        fill(color);
        renderDisplay();
      },
      getCanvas,
      loadFromImage: (img: HTMLImageElement) => {
        loadFromImage(img);
        renderDisplay();
      },
    });
  }, [clear, fill, getCanvas, loadFromImage, onCanvasReady, renderDisplay]);

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

  // Draw a pixel and update display
  const drawPixel = (x: number, y: number) => {
    setPixel(x, y, color);
    renderDisplay();
  };

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDrawing(true);
    const coords = getPixelCoords(e);
    if (coords) {
      drawPixel(coords.x, coords.y);
    }
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (!isDrawing) return;
    const coords = getPixelCoords(e);
    if (coords) {
      drawPixel(coords.x, coords.y);
    }
  };

  const handleMouseUp = () => {
    setIsDrawing(false);
  };

  const handleMouseLeave = () => {
    setIsDrawing(false);
  };

  // Touch handlers
  const handleTouchStart = (e: React.TouchEvent) => {
    e.preventDefault();
    setIsDrawing(true);
    const coords = getPixelCoords(e);
    if (coords) {
      drawPixel(coords.x, coords.y);
    }
  };

  const handleTouchMove = (e: React.TouchEvent) => {
    e.preventDefault();
    if (!isDrawing) return;
    const coords = getPixelCoords(e);
    if (coords) {
      drawPixel(coords.x, coords.y);
    }
  };

  const handleTouchEnd = () => {
    setIsDrawing(false);
  };

  return (
    <div className="pixel-canvas-container">
      <canvas
        ref={displayCanvasRef}
        width={displaySize}
        height={displaySize}
        className="pixel-canvas"
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      />
      <label className="grid-toggle">
        <input
          type="checkbox"
          checked={showGrid}
          onChange={(e) => {
            setShowGrid(e.target.checked);
          }}
        />
        Show grid
      </label>
    </div>
  );
}
