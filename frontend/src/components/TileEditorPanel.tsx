import { useState, useCallback, useRef, useEffect } from "react";
import { flushSync, createPortal } from "react-dom";
import { X, Check } from "lucide-react";
import type { TileCoordinates } from "../types";
import { PixelCanvas } from "./PixelCanvas";
import { ColorPicker } from "./ColorPicker";
import { Toolbar, type Tool } from "./Toolbar";
import { toPngBlob } from "../utils/canvas";
import { getTileImage } from "../api/tiles";
import "./TileEditorPanel.css";

interface TileEditorPanelProps {
  isOpen: boolean;
  tile: TileCoordinates | null;
  onClose: () => void;
  onSave: (tileX: number, tileY: number, pngBlob: Blob) => Promise<void>;
}

const MAX_RECENT_COLORS = 10;

export function TileEditorPanel({ isOpen, tile, onClose, onSave }: TileEditorPanelProps) {
  const [color, setColor] = useState("#000000");
  const [tool, setTool] = useState<Tool>("pencil");
  const [showGrid, setShowGrid] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentColors, setRecentColors] = useState<string[]>([]);
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const [showSavedToast, setShowSavedToast] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);

  // Store canvas helpers from PixelCanvas
  const canvasHelpersRef = useRef<{
    clear: () => void;
    fill: (color: string) => void;
    getCanvas: () => HTMLCanvasElement;
    loadFromImage: (img: HTMLImageElement) => void;
    setShowGrid: (show: boolean) => void;
    undo: () => boolean;
    redo: () => boolean;
    canUndo: boolean;
    canRedo: boolean;
  } | null>(null);

  const handleCanvasReady = useCallback(
    (helpers: {
      clear: () => void;
      fill: (color: string) => void;
      getCanvas: () => HTMLCanvasElement;
      loadFromImage: (img: HTMLImageElement) => void;
      setShowGrid: (show: boolean) => void;
      undo: () => boolean;
      redo: () => boolean;
      canUndo: boolean;
      canRedo: boolean;
    }) => {
      canvasHelpersRef.current = helpers;
      setCanUndo(helpers.canUndo);
      setCanRedo(helpers.canRedo);
    },
    []
  );

  // Update undo/redo state whenever canvas changes
  const updateUndoRedoState = useCallback(() => {
    if (canvasHelpersRef.current) {
      setCanUndo(canvasHelpersRef.current.canUndo);
      setCanRedo(canvasHelpersRef.current.canRedo);
    }
  }, []);

  // Fetch existing tile when tile changes
  useEffect(() => {
    if (!tile || !isOpen) return;

    // Reset changes flag when loading a new tile
    setHasChanges(false);

    // Capture tile coordinates for the async function
    const tileX = tile.x;
    const tileY = tile.y;
    let cancelled = false;

    async function loadExistingTile() {
      setIsLoading(true);
      setError(null);

      try {
        const blob = await getTileImage(tileX, tileY);

        if (cancelled) return;

        if (blob && canvasHelpersRef.current) {
          const url = URL.createObjectURL(blob);
          const img = new Image();
          img.onload = () => {
            if (!cancelled && canvasHelpersRef.current) {
              canvasHelpersRef.current.loadFromImage(img);
              updateUndoRedoState();
            }
            URL.revokeObjectURL(url);
          };
          img.onerror = () => {
            URL.revokeObjectURL(url);
          };
          img.src = url;
        }
      } catch (err) {
        if (!cancelled) {
          console.error("Failed to load tile:", err);
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    const timeout = setTimeout(loadExistingTile, 100);

    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [tile, isOpen, updateUndoRedoState]);

  // Sync grid toggle with canvas
  useEffect(() => {
    canvasHelpersRef.current?.setShowGrid(showGrid);
  }, [showGrid]);

  const handleClear = useCallback(() => {
    canvasHelpersRef.current?.clear();
    updateUndoRedoState();
    setHasChanges(true);
  }, [updateUndoRedoState]);

  const handleUndo = useCallback(() => {
    canvasHelpersRef.current?.undo();
    updateUndoRedoState();
    setHasChanges(true);
  }, [updateUndoRedoState]);

  const handleRedo = useCallback(() => {
    canvasHelpersRef.current?.redo();
    updateUndoRedoState();
    setHasChanges(true);
  }, [updateUndoRedoState]);

  // Called when canvas content changes (drawing)
  const handleCanvasChange = useCallback(() => {
    setHasChanges(true);
  }, []);

  // Add color to recent colors
  const addToRecentColors = useCallback((newColor: string) => {
    setRecentColors((prev) => {
      // Remove if already exists
      const filtered = prev.filter((c) => c !== newColor);
      // Add to front
      return [newColor, ...filtered].slice(0, MAX_RECENT_COLORS);
    });
  }, []);

  // Handle color change - add to recents when user actively selects
  const handleColorChange = useCallback(
    (newColor: string) => {
      setColor(newColor);
      addToRecentColors(newColor);
    },
    [addToRecentColors]
  );

  // Handle eyedropper color pick
  const handleColorPick = useCallback(
    (pickedColor: string) => {
      setColor(pickedColor);
      addToRecentColors(pickedColor);
      // Optionally switch back to pencil after picking
      setTool("pencil");
    },
    [addToRecentColors]
  );

  // Save tile to specific coordinates
  // Returns true if saved, false if error, null if no changes/canvas
  // tileCoords: which tile to save to (important for tile switching)
  // forceSkipCheck: bypass hasChanges check (used during tile switch)
  const saveToTile = useCallback(
    async (tileCoords: TileCoordinates, forceSkipCheck = false): Promise<boolean | null> => {
      if (!canvasHelpersRef.current) return null;
      if (!forceSkipCheck && !hasChanges) return null;

      try {
        const canvas = canvasHelpersRef.current.getCanvas();
        const blob = await toPngBlob(canvas);
        await onSave(tileCoords.x, tileCoords.y, blob);
        setHasChanges(false);
        return true;
      } catch (err) {
        console.error("Failed to save tile:", err);
        setError(err instanceof Error ? err.message : "Failed to save tile");
        return false;
      }
    },
    [onSave, hasChanges]
  );

  // Auto-save and close
  const handleClose = useCallback(async () => {
    if (isSaving || !tile) return;

    // If no changes, just close immediately
    if (!hasChanges) {
      onClose();
      return;
    }

    setIsSaving(true);
    setError(null);

    const saved = await saveToTile(tile);

    if (saved) {
      // Show saved toast briefly - use flushSync to force immediate render
      flushSync(() => {
        setShowSavedToast(true);
      });
      setTimeout(() => {
        setShowSavedToast(false);
        setIsSaving(false);
        onClose();
      }, 800);
    } else if (saved === false) {
      // Error occurred
      setIsSaving(false);
    } else {
      // No changes (shouldn't reach here, but handle gracefully)
      setIsSaving(false);
      onClose();
    }
  }, [isSaving, hasChanges, tile, saveToTile, onClose]);

  // Track previous tile and its changes state to auto-save when switching tiles
  const prevTileRef = useRef<TileCoordinates | null>(null);
  const hadChangesRef = useRef(false);

  // Update hadChangesRef whenever hasChanges changes
  useEffect(() => {
    hadChangesRef.current = hasChanges;
  }, [hasChanges]);

  // Auto-save when tile changes (clicking another tile while editor is open)
  useEffect(() => {
    if (!isOpen) {
      prevTileRef.current = null;
      return;
    }

    // If we had a previous tile and it changed, save the previous one if it had changes
    const prevTile = prevTileRef.current;
    if (prevTile && tile && (prevTile.x !== tile.x || prevTile.y !== tile.y)) {
      // Only save if there were changes to the previous tile
      // Use forceSkipCheck because hasChanges may have been reset by the loading effect
      // IMPORTANT: Save to the PREVIOUS tile coordinates, not the new one
      if (hadChangesRef.current) {
        // Save and show toast
        saveToTile(prevTile, true).then((saved) => {
          if (saved) {
            flushSync(() => {
              setShowSavedToast(true);
            });
            setTimeout(() => {
              setShowSavedToast(false);
            }, 800);
          }
        });
      }
    }

    prevTileRef.current = tile;
  }, [tile, isOpen, saveToTile]);

  // Keyboard shortcuts
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Save and close on Escape
      if (e.key === "Escape") {
        handleClose();
        return;
      }

      // Tool shortcuts (1-4) and grid toggle (G)
      if (!e.metaKey && !e.ctrlKey && !e.altKey) {
        switch (e.key) {
          case "1":
            setTool("pencil");
            return;
          case "2":
            setTool("fill");
            return;
          case "3":
            setTool("eraser");
            return;
          case "4":
            setTool("eyedropper");
            return;
          case "g":
          case "G":
            setShowGrid((prev) => !prev);
            return;
        }
      }

      // Undo: Cmd+Z (Mac) or Ctrl+Z (Windows)
      if ((e.metaKey || e.ctrlKey) && e.key === "z" && !e.shiftKey) {
        e.preventDefault();
        handleUndo();
        return;
      }

      // Redo: Cmd+Shift+Z (Mac) or Ctrl+Shift+Z / Ctrl+Y (Windows)
      if ((e.metaKey || e.ctrlKey) && ((e.key === "z" && e.shiftKey) || e.key === "y")) {
        e.preventDefault();
        handleRedo();
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose, handleUndo, handleRedo]);

  // Render toast via portal so it persists even when panel closes
  const toast = showSavedToast
    ? createPortal(
        <div className="save-toast">
          <Check size={18} />
          Saved
        </div>,
        document.body
      )
    : null;

  if (!isOpen || !tile) return toast;

  return (
    <>
      {toast}
      <div className="tile-editor-panel">
        <div className="tile-editor-panel__header">
          <h2 className="tile-editor-panel__title">
            Tile ({tile.x}, {tile.y})
          </h2>
          <button
            className="tile-editor-panel__close"
            onClick={handleClose}
            aria-label="Save and close"
          >
            <X size={20} />
          </button>
        </div>

        <div className="tile-editor-panel__content">
          {isLoading && (
            <div className="tile-editor-panel__loading">
              <div className="tile-editor-panel__spinner" />
              <span>Loading tile...</span>
            </div>
          )}

          <Toolbar
            tool={tool}
            onToolChange={setTool}
            canUndo={canUndo}
            canRedo={canRedo}
            onUndo={handleUndo}
            onRedo={handleRedo}
            onClear={handleClear}
            showGrid={showGrid}
            onToggleGrid={() => setShowGrid(!showGrid)}
          />

          <PixelCanvas
            color={color}
            tool={tool}
            showGrid={showGrid}
            onColorPick={handleColorPick}
            onChange={handleCanvasChange}
            onCanvasReady={handleCanvasReady}
          />

          <ColorPicker color={color} onChange={handleColorChange} recentColors={recentColors} />

          {error && <div className="tile-editor-panel__error">{error}</div>}
        </div>
      </div>
    </>
  );
}
