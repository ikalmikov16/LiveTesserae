import { useState, useCallback, useRef, useEffect } from "react";
import { flushSync, createPortal } from "react-dom";
import { Check, Crosshair, Save } from "lucide-react";
import type { TileCoordinates } from "../types";
import { PixelCanvas } from "./PixelCanvas";
import { ColorPicker } from "./ColorPicker";
import { Toolbar, type Tool } from "./Toolbar";
import { getTilePixels } from "../api/tiles";
import "./TileEditorPanel.css";

interface TileEditorPanelProps {
  isOpen: boolean;
  tile: TileCoordinates | null;
  onClose: () => void;
  onSave: (tileX: number, tileY: number, pixelData: Uint8Array) => Promise<void>;
  onPanToTile?: () => void;
  onPreviewChange?: (pixelData: Uint8Array | null) => void;
}

const MAX_RECENT_COLORS = 10;

export function TileEditorPanel({
  isOpen,
  tile,
  onClose,
  onSave,
  onPanToTile,
  onPreviewChange,
}: TileEditorPanelProps) {
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
    loadFromRgbBytes: (rgb: Uint8Array) => void;
    toRgbBytes: () => Uint8Array;
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
      loadFromRgbBytes: (rgb: Uint8Array) => void;
      toRgbBytes: () => Uint8Array;
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
        const pixels = await getTilePixels(tileX, tileY);

        if (cancelled) return;

        if (pixels && canvasHelpersRef.current) {
          canvasHelpersRef.current.loadFromRgbBytes(pixels);
          updateUndoRedoState();
          // Emit initial preview
          onPreviewChange?.(pixels);
        } else if (canvasHelpersRef.current) {
          // Empty tile - emit current canvas state
          onPreviewChange?.(canvasHelpersRef.current.toRgbBytes());
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
  }, [tile, isOpen, updateUndoRedoState, onPreviewChange]);

  // Sync grid toggle with canvas
  useEffect(() => {
    canvasHelpersRef.current?.setShowGrid(showGrid);
  }, [showGrid]);

  // Throttle preview updates to avoid performance issues during drawing
  const previewThrottleRef = useRef<number | null>(null);

  // Cleanup throttle timeout on unmount
  useEffect(() => {
    return () => {
      if (previewThrottleRef.current) {
        clearTimeout(previewThrottleRef.current);
      }
    };
  }, []);

  // Emit current canvas state as preview (immediate, for undo/redo/clear)
  const emitPreview = useCallback(() => {
    if (onPreviewChange && canvasHelpersRef.current) {
      onPreviewChange(canvasHelpersRef.current.toRgbBytes());
    }
  }, [onPreviewChange]);

  // Throttled preview emit for drawing (limits updates to ~30fps)
  const emitPreviewThrottled = useCallback(() => {
    if (!onPreviewChange || !canvasHelpersRef.current) return;

    if (previewThrottleRef.current) return; // Already scheduled

    previewThrottleRef.current = window.setTimeout(() => {
      previewThrottleRef.current = null;
      if (canvasHelpersRef.current) {
        onPreviewChange(canvasHelpersRef.current.toRgbBytes());
      }
    }, 33); // ~30fps
  }, [onPreviewChange]);

  const handleClear = useCallback(() => {
    canvasHelpersRef.current?.clear();
    updateUndoRedoState();
    setHasChanges(true);
    emitPreview();
  }, [updateUndoRedoState, emitPreview]);

  const handleUndo = useCallback(() => {
    canvasHelpersRef.current?.undo();
    updateUndoRedoState();
    setHasChanges(true);
    emitPreview();
  }, [updateUndoRedoState, emitPreview]);

  const handleRedo = useCallback(() => {
    canvasHelpersRef.current?.redo();
    updateUndoRedoState();
    setHasChanges(true);
    emitPreview();
  }, [updateUndoRedoState, emitPreview]);

  // Called when canvas content changes (drawing)
  const handleCanvasChange = useCallback(() => {
    setHasChanges(true);
    // Emit throttled preview for smooth drawing
    emitPreviewThrottled();
  }, [emitPreviewThrottled]);

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
        const rgbBytes = canvasHelpersRef.current.toRgbBytes();
        await onSave(tileCoords.x, tileCoords.y, rgbBytes);
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
      onPreviewChange?.(null);
      onClose();
      return;
    }

    setIsSaving(true);
    setError(null);

    const saved = await saveToTile(tile);

    if (saved) {
      // Only now is the preview safe to drop: the save handler has written the
      // pixels into the canvas cache. Clearing it up front, as this used to,
      // uncovered the tile's pre-edit pixels for as long as the save took —
      // and left them showing for good if the update never came back.
      onPreviewChange?.(null);

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
      // Save failed and the editor stays open — keep the preview on the canvas
      // so the artwork is still visible while the user retries.
      setIsSaving(false);
    } else {
      // No changes (shouldn't reach here, but handle gracefully)
      onPreviewChange?.(null);
      setIsSaving(false);
      onClose();
    }
  }, [isSaving, hasChanges, tile, saveToTile, onClose, onPreviewChange]);

  // Save without closing. The editor used to commit only on close, which made
  // "live" mean per-close and lost the drawing outright if the tab went away.
  const handleSave = useCallback(async () => {
    if (isSaving || !tile || !hasChanges) return;

    setIsSaving(true);
    setError(null);
    const saved = await saveToTile(tile);
    setIsSaving(false);

    if (saved) {
      // The preview deliberately stays on the canvas: unlike handleClose, the
      // editor remains open and the user is still working on this tile.
      flushSync(() => {
        setShowSavedToast(true);
      });
      setTimeout(() => setShowSavedToast(false), 800);
    }
  }, [isSaving, tile, hasChanges, saveToTile]);

  // Track previous tile and its changes state to auto-save when switching tiles
  const prevTileRef = useRef<TileCoordinates | null>(null);
  const hadChangesRef = useRef(false);
  const isSavingRef = useRef(false);
  const flushingRef = useRef(false);

  // Update hadChangesRef whenever hasChanges changes
  useEffect(() => {
    hadChangesRef.current = hasChanges;
  }, [hasChanges]);

  // Mirrored into a ref so the teardown handlers below can read it without
  // re-registering on every save.
  useEffect(() => {
    isSavingRef.current = isSaving;
  }, [isSaving]);

  // Flush unsaved work when the page is torn down or backgrounded.
  //
  // Both events are needed and neither is redundant: `pagehide` is the reliable
  // teardown signal on iOS (`beforeunload`/`unload` are not), while
  // `visibilitychange` fires when the user merely switches apps — which is the
  // moment an iOS tab becomes eligible for eviction, long before any teardown
  // event would arrive. Whichever lands first wins; `flushingRef` stops the
  // second from sending a duplicate.
  //
  // This depends on `keepalive` in `saveTile`. Without it the request is
  // cancelled as the document goes away and this whole path is a no-op.
  useEffect(() => {
    if (!isOpen || !tile) return;

    const flush = () => {
      if (flushingRef.current || isSavingRef.current) return;
      if (!hadChangesRef.current || !canvasHelpersRef.current) return;

      flushingRef.current = true;
      const rgbBytes = canvasHelpersRef.current.toRgbBytes();
      void Promise.resolve(onSave(tile.x, tile.y, rgbBytes))
        // If the tab survives (an app switch rather than a close), reflect that
        // the work is committed so a later close does not send it again.
        .then(() => setHasChanges(false))
        .catch(() => {
          // The document is usually going away; there is no one to tell.
        })
        .finally(() => {
          flushingRef.current = false;
        });
    };

    const handleVisibility = () => {
      if (document.visibilityState === "hidden") flush();
    };

    window.addEventListener("pagehide", flush);
    document.addEventListener("visibilitychange", handleVisibility);
    return () => {
      window.removeEventListener("pagehide", flush);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [isOpen, tile, onSave]);

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

      // Cmd/Ctrl+S saves without closing. preventDefault or the browser opens
      // its own "save page" dialog over the editor.
      if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        handleSave();
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
  }, [isOpen, handleClose, handleSave, handleUndo, handleRedo]);

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
          <div className="tile-editor-panel__header-actions">
            {onPanToTile && (
              <button
                className="tile-editor-panel__header-btn"
                onClick={onPanToTile}
                title="Pan to tile"
              >
                <Crosshair size={18} />
              </button>
            )}
            <button
              className="tile-editor-panel__header-btn"
              onClick={handleSave}
              disabled={!hasChanges || isSaving}
              aria-label="Save tile"
              title="Save tile (⌘S)"
            >
              <Save size={18} />
            </button>
            <button
              className="tile-editor-panel__close"
              onClick={handleClose}
              aria-label="Save and close"
            >
              <Check size={20} />
            </button>
          </div>
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
