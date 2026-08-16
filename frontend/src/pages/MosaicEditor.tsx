import { useState, useCallback, useRef, useEffect } from "react";

import { MosaicCanvas } from "../components/MosaicCanvas";
import { TileEditorPanel } from "../components/TileEditorPanel";
import { MiniMap } from "../components/MiniMap";
import { saveTile } from "../api/tiles";
import { useWebSocket } from "../hooks/useWebSocket";
import {
  getVisibleChunks,
  diffChunkSubscriptions,
  selectSubscribableChunks,
} from "../utils/chunks";
import { base64ToUint8Array } from "../utils/pixels";
import { MOSAIC_CONFIG, getRenderLevel } from "../config";
import type {
  TileCoordinates,
  TileUpdateMessage,
  TileWithPixels,
  ChunkUpdatedMessage,
  OverviewUpdatedMessage,
} from "../types";

const { TILE_SIZE } = MOSAIC_CONFIG;

interface TilePreview {
  x: number;
  y: number;
  pixelData: Uint8Array;
}

export function MosaicEditor() {
  useEffect(() => {
    document.title = "Live Tesserae — Editor";
  }, []);

  const [selectedTile, setSelectedTile] = useState<TileCoordinates | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [tileUpdate, setTileUpdate] = useState<TileWithPixels | null>(null);
  const [tilePreview, setTilePreview] = useState<TilePreview | null>(null);

  const [chunkUpdate, setChunkUpdate] = useState<ChunkUpdatedMessage | null>(null);
  const [overviewUpdate, setOverviewUpdate] = useState<OverviewUpdatedMessage | null>(null);

  const [overviewImage, setOverviewImage] = useState<HTMLImageElement | null>(null);
  const [viewportState, setViewportState] = useState({ x: 0, y: 0, zoom: 0.02 });
  const [navigateTo, setNavigateTo] = useState<{ x: number; y: number } | null>(null);
  const [canvasSize, setCanvasSize] = useState({
    width: window.innerWidth,
    height: window.innerHeight,
  });

  useEffect(() => {
    const onResize = () => setCanvasSize({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const subscribedChunksRef = useRef<string[]>([]);
  const subscriptionTimeoutRef = useRef<number | null>(null);
  // Latest viewport, readable without making effects depend on every pan.
  const viewportRef = useRef({ x: 0, y: 0, zoom: 0.02 });

  /**
   * Chunks this client should be subscribed to right now.
   *
   * Capped to what one connection may hold, because the server drops the
   * excess silently. Empty at zoom level 0: the overview is a global broadcast,
   * so subscribing to every visible chunk there buys nothing and would spend
   * the whole budget on chunks the user cannot see detail in anyway.
   */
  const computeSubscriptionIntent = useCallback(
    (offsetX: number, offsetY: number, zoom: number): string[] => {
      if (getRenderLevel(TILE_SIZE * zoom) === 0) return [];

      const visibleWidth = window.innerWidth / zoom;
      const visibleHeight = window.innerHeight / zoom;
      const visible = getVisibleChunks(offsetX, offsetY, visibleWidth, visibleHeight);

      return selectSubscribableChunks(
        visible,
        offsetX + visibleWidth / 2,
        offsetY + visibleHeight / 2
      );
    },
    []
  );

  const handleWebSocketTileUpdate = useCallback((message: TileUpdateMessage) => {
    const pixelData = base64ToUint8Array(message.pixels);
    setTileUpdate({ x: message.x, y: message.y, pixelData });
  }, []);

  const handleChunkUpdate = useCallback((message: ChunkUpdatedMessage) => {
    setChunkUpdate(message);
  }, []);

  const handleOverviewUpdate = useCallback((message: OverviewUpdatedMessage) => {
    setOverviewUpdate(message);
  }, []);

  const { isConnected, connectionEpoch, subscribe, unsubscribe } = useWebSocket({
    onTileUpdate: handleWebSocketTileUpdate,
    onChunkUpdate: handleChunkUpdate,
    onOverviewUpdate: handleOverviewUpdate,
  });

  const handleViewportChange = useCallback(
    (offsetX: number, offsetY: number, zoom: number) => {
      setViewportState({ x: offsetX, y: offsetY, zoom });
      viewportRef.current = { x: offsetX, y: offsetY, zoom };

      if (subscriptionTimeoutRef.current) {
        clearTimeout(subscriptionTimeoutRef.current);
      }

      subscriptionTimeoutRef.current = window.setTimeout(() => {
        if (!isConnected) return;

        const newChunks = computeSubscriptionIntent(offsetX, offsetY, zoom);

        const { subscribe: toSub, unsubscribe: toUnsub } = diffChunkSubscriptions(
          subscribedChunksRef.current,
          newChunks
        );

        // Unsubscribe first: the server counts subscriptions against a per-
        // connection cap, so subscribing before releasing the chunks we are
        // leaving can push the new ones over the limit and get them dropped.
        if (toUnsub.length > 0) unsubscribe(toUnsub);
        if (toSub.length > 0) subscribe(toSub);

        subscribedChunksRef.current = newChunks;
      }, 150);
    },
    [isConnected, subscribe, unsubscribe, computeSubscriptionIntent]
  );

  // Re-subscribe on every new connection. The server throws away a connection's
  // subscriptions when it closes, so after a reconnect our ref describes state
  // that no longer exists and the next diff would send nothing at all — live
  // updates would stop silently while the badge still read "Live".
  useEffect(() => {
    if (connectionEpoch === 0) return;

    // Drop any in-flight diff first; it was computed against the dead socket.
    if (subscriptionTimeoutRef.current) {
      clearTimeout(subscriptionTimeoutRef.current);
      subscriptionTimeoutRef.current = null;
    }

    const { x, y, zoom } = viewportRef.current;
    const chunks = computeSubscriptionIntent(x, y, zoom);

    // No unsubscribe: the server's set for this connection is already empty.
    subscribedChunksRef.current = chunks;
    if (chunks.length > 0) subscribe(chunks);
  }, [connectionEpoch, subscribe, computeSubscriptionIntent]);

  useEffect(() => {
    return () => {
      if (subscriptionTimeoutRef.current) clearTimeout(subscriptionTimeoutRef.current);
    };
  }, []);

  const handleOverviewLoad = useCallback((image: HTMLImageElement) => {
    setOverviewImage(image);
  }, []);

  const handleMiniMapNavigate = useCallback((x: number, y: number) => {
    setNavigateTo({ x, y });
    setTimeout(() => setNavigateTo(null), 0);
  }, []);

  const handleGoToTile = useCallback((x: number, y: number) => {
    setSelectedTile({ x, y });
    setEditorOpen(true);
  }, []);

  const handlePanToTile = useCallback(() => {
    if (!selectedTile) return;
    const worldX = (selectedTile.x + 0.5) * TILE_SIZE - canvasSize.width / viewportState.zoom / 2;
    const worldY = (selectedTile.y + 0.5) * TILE_SIZE - canvasSize.height / viewportState.zoom / 2;
    setNavigateTo({ x: worldX, y: worldY });
    setTimeout(() => setNavigateTo(null), 0);
  }, [selectedTile, canvasSize.width, canvasSize.height, viewportState.zoom]);

  const handlePreviewChange = useCallback(
    (pixelData: Uint8Array | null) => {
      if (!selectedTile || !pixelData) {
        setTilePreview(null);
        return;
      }
      setTilePreview({ x: selectedTile.x, y: selectedTile.y, pixelData });
    },
    [selectedTile]
  );

  const handleTileClick = (coords: TileCoordinates) => {
    setSelectedTile(coords);
    setEditorOpen(true);
  };

  const handleCloseEditor = () => {
    setEditorOpen(false);
    setTilePreview(null);
  };

  const handleSaveTile = useCallback(
    async (tileX: number, tileY: number, pixelData: Uint8Array) => {
      await saveTile(tileX, tileY, pixelData);

      // Paint it locally instead of waiting for the WebSocket echo to come
      // back. That echo was the *only* thing that ever wrote a saved tile into
      // the canvas cache, so any dropped or unsubscribed update made the user's
      // own artwork visibly revert the moment the editor closed.
      setTileUpdate({ x: tileX, y: tileY, pixelData });
    },
    []
  );

  const handleTileUpdateProcessed = useCallback(() => setTileUpdate(null), []);
  const handleChunkUpdateProcessed = useCallback(() => setChunkUpdate(null), []);
  const handleOverviewUpdateProcessed = useCallback(() => setOverviewUpdate(null), []);

  return (
    <div style={{ width: "100%", height: "100%", overflow: "hidden" }}>
      <MosaicCanvas
        onTileClick={handleTileClick}
        tileUpdate={tileUpdate}
        onTileUpdateProcessed={handleTileUpdateProcessed}
        chunkUpdate={chunkUpdate}
        onChunkUpdateProcessed={handleChunkUpdateProcessed}
        overviewUpdate={overviewUpdate}
        onOverviewUpdateProcessed={handleOverviewUpdateProcessed}
        onViewportChange={handleViewportChange}
        onOverviewLoad={handleOverviewLoad}
        navigateTo={navigateTo}
        tilePreview={tilePreview}
        selectedTile={editorOpen ? selectedTile : null}
      />
      <MiniMap
        overviewImage={overviewImage}
        viewportX={viewportState.x}
        viewportY={viewportState.y}
        viewportZoom={viewportState.zoom}
        canvasWidth={canvasSize.width}
        canvasHeight={canvasSize.height}
        onNavigate={handleMiniMapNavigate}
        editingTile={editorOpen ? selectedTile : null}
        onGoToTile={handleGoToTile}
      />
      <TileEditorPanel
        isOpen={editorOpen}
        tile={selectedTile}
        onClose={handleCloseEditor}
        onSave={handleSaveTile}
        onPanToTile={handlePanToTile}
        onPreviewChange={handlePreviewChange}
      />
      <div
        role="status"
        aria-live="polite"
        style={{
          position: "fixed",
          bottom: 10,
          left: 10,
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 12,
          backgroundColor: isConnected ? "#22c55e" : "#ef4444",
          color: "white",
          zIndex: 100,
        }}
      >
        {isConnected ? "Live" : "Disconnected"}
      </div>
    </div>
  );
}
