import { useState, useCallback, useRef, useEffect } from "react";
import type { TileCoordinates } from "../types";
import { PixelCanvas } from "./PixelCanvas";
import { ColorPicker } from "./ColorPicker";
import { toPngBlob } from "../utils/canvas";
import { getTileImage } from "../api/tiles";
import "./TileEditorModal.css";

interface TileEditorModalProps {
  tile: TileCoordinates;
  onClose: () => void;
  onSave: (pngBlob: Blob) => Promise<void>;
}

export function TileEditorModal({ tile, onClose, onSave }: TileEditorModalProps) {
  const [color, setColor] = useState("#000000");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Store canvas helpers from PixelCanvas
  const canvasHelpersRef = useRef<{
    clear: () => void;
    fill: (color: string) => void;
    getCanvas: () => HTMLCanvasElement;
    loadFromImage: (img: HTMLImageElement) => void;
  } | null>(null);

  const handleCanvasReady = useCallback(
    (helpers: {
      clear: () => void;
      fill: (color: string) => void;
      getCanvas: () => HTMLCanvasElement;
      loadFromImage: (img: HTMLImageElement) => void;
    }) => {
      canvasHelpersRef.current = helpers;
    },
    []
  );

  // Fetch existing tile on mount
  useEffect(() => {
    let cancelled = false;

    async function loadExistingTile() {
      setIsLoading(true);
      setError(null);

      try {
        const blob = await getTileImage(tile.x, tile.y);

        if (cancelled) return;

        if (blob && canvasHelpersRef.current) {
          // Convert blob to image and load into canvas
          const url = URL.createObjectURL(blob);
          const img = new Image();
          img.onload = () => {
            if (!cancelled && canvasHelpersRef.current) {
              canvasHelpersRef.current.loadFromImage(img);
            }
            URL.revokeObjectURL(url);
          };
          img.onerror = () => {
            URL.revokeObjectURL(url);
          };
          img.src = url;
        }
        // If blob is null, tile doesn't exist yet (404), canvas stays blank
      } catch (err) {
        if (!cancelled) {
          console.error("Failed to load tile:", err);
          // Don't show error for loading - just start with blank canvas
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    // Small delay to ensure canvas helpers are ready
    const timeout = setTimeout(loadExistingTile, 100);

    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
  }, [tile.x, tile.y]);

  const handleClear = () => {
    canvasHelpersRef.current?.clear();
  };

  const handleFill = () => {
    canvasHelpersRef.current?.fill(color);
  };

  const handleSave = async () => {
    if (!canvasHelpersRef.current) return;

    setIsSaving(true);
    setError(null);

    try {
      const canvas = canvasHelpersRef.current.getCanvas();
      const blob = await toPngBlob(canvas);
      await onSave(blob);
    } catch (err) {
      console.error("Failed to save tile:", err);
      setError(err instanceof Error ? err.message : "Failed to save tile");
    } finally {
      setIsSaving(false);
    }
  };

  // Close on backdrop click
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget && !isSaving) {
      onClose();
    }
  };

  // Close on Escape key
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape" && !isSaving) {
      onClose();
    }
  };

  return (
    <div
      className="modal-backdrop"
      onClick={handleBackdropClick}
      onKeyDown={handleKeyDown}
      tabIndex={-1}
    >
      <div className="modal-container" role="dialog" aria-modal="true">
        <div className="modal-header">
          <h2 className="modal-title">
            Editing Tile ({tile.x}, {tile.y})
          </h2>
          <button
            className="modal-close-btn"
            onClick={onClose}
            disabled={isSaving}
            aria-label="Close"
          >
            &times;
          </button>
        </div>

        <div className="modal-body">
          {isLoading && (
            <div className="loading-overlay">
              <div className="loading-spinner" />
              <span>Loading tile...</span>
            </div>
          )}
          <PixelCanvas color={color} onCanvasReady={handleCanvasReady} />

          <div className="editor-controls">
            <ColorPicker color={color} onChange={setColor} />
          </div>

          {error && <div className="error-message">{error}</div>}
        </div>

        <div className="modal-footer">
          <div className="modal-footer-left">
            <button
              className="btn btn-secondary"
              onClick={handleClear}
              disabled={isSaving || isLoading}
            >
              Clear
            </button>
            <button
              className="btn btn-secondary"
              onClick={handleFill}
              disabled={isSaving || isLoading}
              title="Fill entire tile with selected color"
            >
              Fill
            </button>
          </div>
          <div className="modal-footer-right">
            <button className="btn btn-secondary" onClick={onClose} disabled={isSaving}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleSave}
              disabled={isSaving || isLoading}
            >
              {isSaving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
