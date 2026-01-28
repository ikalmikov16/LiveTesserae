import { useRef, useCallback } from "react";
import { hexToRgb } from "../utils/canvas";
import { MOSAIC_CONFIG } from "../config";

const CANVAS_SIZE = MOSAIC_CONFIG.TILE_SIZE; // 32

export function usePixelCanvas() {
  // Hidden canvas for the actual 32x32 pixel data
  const pixelCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);

  // Initialize the hidden canvas and context
  const initCanvas = useCallback(() => {
    if (!pixelCanvasRef.current) {
      pixelCanvasRef.current = document.createElement("canvas");
      pixelCanvasRef.current.width = CANVAS_SIZE;
      pixelCanvasRef.current.height = CANVAS_SIZE;
      
      // Use willReadFrequently for better performance with getImageData
      ctxRef.current = pixelCanvasRef.current.getContext("2d", { 
        willReadFrequently: true 
      });
      
      // Fill with white initially
      if (ctxRef.current) {
        ctxRef.current.fillStyle = "#ffffff";
        ctxRef.current.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      }
    }
    return { canvas: pixelCanvasRef.current, ctx: ctxRef.current };
  }, []);

  // Set a single pixel
  const setPixel = useCallback(
    (x: number, y: number, color: string) => {
      const { ctx } = initCanvas();
      if (!ctx) return;

      // Ensure coordinates are within bounds
      if (x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE) return;

      const { r, g, b } = hexToRgb(color);
      const imageData = ctx.getImageData(x, y, 1, 1);
      imageData.data[0] = r;
      imageData.data[1] = g;
      imageData.data[2] = b;
      imageData.data[3] = 255; // Full opacity
      ctx.putImageData(imageData, x, y);
    },
    [initCanvas]
  );

  // Clear the canvas (fill with white)
  const clear = useCallback(() => {
    const { ctx } = initCanvas();
    if (!ctx) return;

    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
  }, [initCanvas]);

  // Fill the entire canvas with a color
  const fill = useCallback(
    (color: string) => {
      const { ctx } = initCanvas();
      if (!ctx) return;

      ctx.fillStyle = color;
      ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    },
    [initCanvas]
  );

  // Get the hidden canvas element (for reading pixel data or exporting)
  const getCanvas = useCallback(() => {
    const { canvas } = initCanvas();
    return canvas;
  }, [initCanvas]);

  // Get pixel color at position
  const getPixel = useCallback(
    (x: number, y: number): string => {
      const { ctx } = initCanvas();
      if (!ctx) return "#ffffff";

      if (x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE) {
        return "#ffffff";
      }

      const imageData = ctx.getImageData(x, y, 1, 1);
      const r = imageData.data[0];
      const g = imageData.data[1];
      const b = imageData.data[2];

      return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
    },
    [initCanvas]
  );

  // Load from existing image data (for editing existing tiles)
  const loadFromImage = useCallback(
    (img: HTMLImageElement) => {
      const { ctx } = initCanvas();
      if (!ctx) return;

      ctx.clearRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      ctx.drawImage(img, 0, 0, CANVAS_SIZE, CANVAS_SIZE);
    },
    [initCanvas]
  );

  return {
    setPixel,
    getPixel,
    clear,
    fill,
    getCanvas,
    loadFromImage,
    canvasSize: CANVAS_SIZE,
  };
}
