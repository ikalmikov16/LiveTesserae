import { useRef, useCallback, useState } from "react";
import { hexToRgb } from "../utils/canvas";
import { MOSAIC_CONFIG } from "../config";

const CANVAS_SIZE = MOSAIC_CONFIG.TILE_SIZE; // 32
const MAX_HISTORY = 50;

export function usePixelCanvas() {
  // Hidden canvas for the actual 32x32 pixel data
  const pixelCanvasRef = useRef<HTMLCanvasElement | null>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);

  // History for undo/redo
  const [history, setHistory] = useState<ImageData[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);

  // Initialize the hidden canvas and context
  const initCanvas = useCallback(() => {
    if (!pixelCanvasRef.current) {
      pixelCanvasRef.current = document.createElement("canvas");
      pixelCanvasRef.current.width = CANVAS_SIZE;
      pixelCanvasRef.current.height = CANVAS_SIZE;

      // Use willReadFrequently for better performance with getImageData
      ctxRef.current = pixelCanvasRef.current.getContext("2d", {
        willReadFrequently: true,
      });

      // Fill with white initially
      if (ctxRef.current) {
        ctxRef.current.fillStyle = "#ffffff";
        ctxRef.current.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      }
    }
    return { canvas: pixelCanvasRef.current, ctx: ctxRef.current };
  }, []);

  // Save current state to history
  const saveToHistory = useCallback(() => {
    const { ctx } = initCanvas();
    if (!ctx) return;

    const imageData = ctx.getImageData(0, 0, CANVAS_SIZE, CANVAS_SIZE);

    setHistory((prev) => {
      // Remove any future history if we're not at the end
      const newHistory = prev.slice(0, historyIndex + 1);
      // Add new state
      newHistory.push(imageData);
      // Limit history size
      if (newHistory.length > MAX_HISTORY) {
        newHistory.shift();
      }
      return newHistory;
    });
    setHistoryIndex((prev) => Math.min(prev + 1, MAX_HISTORY - 1));
  }, [initCanvas, historyIndex]);

  // Undo
  const undo = useCallback(() => {
    if (historyIndex <= 0) return false;

    const { ctx } = initCanvas();
    if (!ctx) return false;

    const newIndex = historyIndex - 1;
    const imageData = history[newIndex];
    if (imageData) {
      ctx.putImageData(imageData, 0, 0);
      setHistoryIndex(newIndex);
      return true;
    }
    return false;
  }, [initCanvas, history, historyIndex]);

  // Redo
  const redo = useCallback(() => {
    if (historyIndex >= history.length - 1) return false;

    const { ctx } = initCanvas();
    if (!ctx) return false;

    const newIndex = historyIndex + 1;
    const imageData = history[newIndex];
    if (imageData) {
      ctx.putImageData(imageData, 0, 0);
      setHistoryIndex(newIndex);
      return true;
    }
    return false;
  }, [initCanvas, history, historyIndex]);

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

    saveToHistory();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
  }, [initCanvas, saveToHistory]);

  // Fill the entire canvas with a color
  const fill = useCallback(
    (color: string) => {
      const { ctx } = initCanvas();
      if (!ctx) return;

      saveToHistory();
      ctx.fillStyle = color;
      ctx.fillRect(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    },
    [initCanvas, saveToHistory]
  );

  // Flood fill (bucket tool)
  const floodFill = useCallback(
    (startX: number, startY: number, fillColor: string) => {
      const { ctx } = initCanvas();
      if (!ctx) return;

      if (startX < 0 || startX >= CANVAS_SIZE || startY < 0 || startY >= CANVAS_SIZE) return;

      saveToHistory();

      const imageData = ctx.getImageData(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      const data = imageData.data;

      // Get target color (color at start position)
      const startIdx = (startY * CANVAS_SIZE + startX) * 4;
      const targetR = data[startIdx];
      const targetG = data[startIdx + 1];
      const targetB = data[startIdx + 2];

      // Get fill color
      const { r: fillR, g: fillG, b: fillB } = hexToRgb(fillColor);

      // If target color is same as fill color, nothing to do
      if (targetR === fillR && targetG === fillG && targetB === fillB) {
        return;
      }

      // BFS flood fill
      const stack: [number, number][] = [[startX, startY]];
      const visited = new Set<string>();

      while (stack.length > 0) {
        const [x, y] = stack.pop()!;
        const key = `${x},${y}`;

        if (visited.has(key)) continue;
        if (x < 0 || x >= CANVAS_SIZE || y < 0 || y >= CANVAS_SIZE) continue;

        const idx = (y * CANVAS_SIZE + x) * 4;

        // Check if this pixel matches target color
        if (data[idx] !== targetR || data[idx + 1] !== targetG || data[idx + 2] !== targetB) {
          continue;
        }

        visited.add(key);

        // Fill this pixel
        data[idx] = fillR;
        data[idx + 1] = fillG;
        data[idx + 2] = fillB;
        data[idx + 3] = 255;

        // Add neighbors
        stack.push([x + 1, y], [x - 1, y], [x, y + 1], [x, y - 1]);
      }

      ctx.putImageData(imageData, 0, 0);
    },
    [initCanvas, saveToHistory]
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

      // Save initial state to history
      const imageData = ctx.getImageData(0, 0, CANVAS_SIZE, CANVAS_SIZE);
      setHistory([imageData]);
      setHistoryIndex(0);
    },
    [initCanvas]
  );

  // Reset history (for new canvas)
  const resetHistory = useCallback(() => {
    const { ctx } = initCanvas();
    if (!ctx) return;

    const imageData = ctx.getImageData(0, 0, CANVAS_SIZE, CANVAS_SIZE);
    setHistory([imageData]);
    setHistoryIndex(0);
  }, [initCanvas]);

  // Start drawing action (save state before drawing)
  const beginDrawing = useCallback(() => {
    saveToHistory();
  }, [saveToHistory]);

  return {
    setPixel,
    getPixel,
    clear,
    fill,
    floodFill,
    getCanvas,
    loadFromImage,
    resetHistory,
    beginDrawing,
    undo,
    redo,
    canUndo: historyIndex > 0,
    canRedo: historyIndex < history.length - 1,
    canvasSize: CANVAS_SIZE,
  };
}
