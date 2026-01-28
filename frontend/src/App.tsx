import { useState, useCallback, useRef, useEffect } from "react";
import "./App.css";
import { MosaicCanvas } from "./components/MosaicCanvas";
import { TileEditorPanel } from "./components/TileEditorPanel";
import { MiniMap } from "./components/MiniMap";
import { saveTile } from "./api/tiles";
import { useWebSocket } from "./hooks/useWebSocket";
import { getVisibleChunks, diffChunkSubscriptions } from "./utils/chunks";
import type { TileCoordinates, TileUpdateMessage, TileWithImage } from "./types";

function App() {
  const [selectedTile, setSelectedTile] = useState<TileCoordinates | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [tileUpdate, setTileUpdate] = useState<TileWithImage | null>(null);

  // Shared state for MiniMap
  const [overviewImage, setOverviewImage] = useState<HTMLImageElement | null>(null);
  const [viewportState, setViewportState] = useState({ x: 0, y: 0, zoom: 0.02 });
  const [navigateTo, setNavigateTo] = useState<{ x: number; y: number } | null>(null);
  const [canvasSize] = useState({ width: window.innerWidth, height: window.innerHeight });

  // Track subscribed chunks with ref to avoid stale closures in callback
  const subscribedChunksRef = useRef<string[]>([]);
  const subscriptionTimeoutRef = useRef<number | null>(null);

  // Handle real-time tile updates from WebSocket
  const handleWebSocketTileUpdate = useCallback((message: TileUpdateMessage) => {
    console.log(`WebSocket: Tile update received (${message.x}, ${message.y})`);

    setTileUpdate({
      x: message.x,
      y: message.y,
      imageData: message.image,
    });
  }, []);

  // Connect to WebSocket
  const { isConnected, subscribe, unsubscribe } = useWebSocket({
    onTileUpdate: handleWebSocketTileUpdate,
  });

  // Handle viewport changes - update minimap immediately, debounce subscriptions
  const handleViewportChange = useCallback(
    (offsetX: number, offsetY: number, zoom: number) => {
      // Update viewport state for MiniMap (immediate for responsiveness)
      setViewportState({ x: offsetX, y: offsetY, zoom });

      // Debounce chunk subscription updates to avoid spamming WebSocket
      if (subscriptionTimeoutRef.current) {
        clearTimeout(subscriptionTimeoutRef.current);
      }

      subscriptionTimeoutRef.current = window.setTimeout(() => {
        if (!isConnected) return;

        // Calculate visible area in world coordinates
        const visibleWidth = window.innerWidth / zoom;
        const visibleHeight = window.innerHeight / zoom;

        const newChunks = getVisibleChunks(offsetX, offsetY, visibleWidth, visibleHeight);

        const { subscribe: toSub, unsubscribe: toUnsub } = diffChunkSubscriptions(
          subscribedChunksRef.current,
          newChunks
        );

        if (toSub.length > 0) {
          subscribe(toSub);
        }
        if (toUnsub.length > 0) {
          unsubscribe(toUnsub);
        }

        subscribedChunksRef.current = newChunks;
      }, 150);
    },
    [isConnected, subscribe, unsubscribe]
  );

  // Cleanup subscription timeout on unmount
  useEffect(() => {
    return () => {
      if (subscriptionTimeoutRef.current) {
        clearTimeout(subscriptionTimeoutRef.current);
      }
    };
  }, []);

  // Handle overview image loaded (for MiniMap)
  const handleOverviewLoad = useCallback((image: HTMLImageElement) => {
    setOverviewImage(image);
  }, []);

  // Handle MiniMap navigation
  const handleMiniMapNavigate = useCallback((x: number, y: number) => {
    setNavigateTo({ x, y });
    // Clear after a tick to allow re-navigation to same coordinates
    setTimeout(() => setNavigateTo(null), 0);
  }, []);

  const handleTileClick = (coords: TileCoordinates) => {
    setSelectedTile(coords);
    setEditorOpen(true);
  };

  const handleCloseEditor = () => {
    setEditorOpen(false);
  };

  const handleSaveTile = useCallback(async (tileX: number, tileY: number, pngBlob: Blob) => {
    await saveTile(tileX, tileY, pngBlob);
    // Note: The tile will appear via WebSocket broadcast
    // Don't close editor here - let the caller decide
  }, []);

  // Clear tileUpdate after MosaicCanvas processes it
  const handleTileUpdateProcessed = useCallback(() => {
    setTileUpdate(null);
  }, []);

  return (
    <>
      <MosaicCanvas
        onTileClick={handleTileClick}
        tileUpdate={tileUpdate}
        onTileUpdateProcessed={handleTileUpdateProcessed}
        onViewportChange={handleViewportChange}
        onOverviewLoad={handleOverviewLoad}
        navigateTo={navigateTo}
      />
      <MiniMap
        overviewImage={overviewImage}
        viewportX={viewportState.x}
        viewportY={viewportState.y}
        viewportZoom={viewportState.zoom}
        canvasWidth={canvasSize.width}
        canvasHeight={canvasSize.height}
        onNavigate={handleMiniMapNavigate}
      />
      <TileEditorPanel
        isOpen={editorOpen}
        tile={selectedTile}
        onClose={handleCloseEditor}
        onSave={handleSaveTile}
      />
      {/* Connection status indicator */}
      <div
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
    </>
  );
}

export default App;
