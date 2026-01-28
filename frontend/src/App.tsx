import { useState, useCallback, useRef } from "react";
import "./App.css";
import { MosaicCanvas } from "./components/MosaicCanvas";
import { TileEditorModal } from "./components/TileEditorModal";
import { saveTile } from "./api/tiles";
import { useWebSocket } from "./hooks/useWebSocket";
import { getVisibleChunks, diffChunkSubscriptions } from "./utils/chunks";
import type { TileCoordinates, TileUpdateMessage, TileWithImage } from "./types";

function App() {
  const [selectedTile, setSelectedTile] = useState<TileCoordinates | null>(null);
  const [tileUpdate, setTileUpdate] = useState<TileWithImage | null>(null);

  // Track subscribed chunks with ref to avoid stale closures in callback
  const subscribedChunksRef = useRef<string[]>([]);

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

  // Handle viewport changes - update chunk subscriptions
  const handleViewportChange = useCallback(
    (offsetX: number, offsetY: number, zoom: number) => {
      if (!isConnected) return;

      // Calculate visible area in world coordinates
      const visibleWidth = window.innerWidth / zoom;
      const visibleHeight = window.innerHeight / zoom;

      const newChunks = getVisibleChunks(
        offsetX,
        offsetY,
        visibleWidth,
        visibleHeight
      );

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
    },
    [isConnected, subscribe, unsubscribe]
  );

  const handleTileClick = (coords: TileCoordinates) => {
    setSelectedTile(coords);
  };

  const handleCloseEditor = () => {
    setSelectedTile(null);
  };

  const handleSaveTile = useCallback(
    async (pngBlob: Blob) => {
      if (!selectedTile) return;

      await saveTile(selectedTile.x, selectedTile.y, pngBlob);

      // Note: The tile will appear via WebSocket broadcast
      setSelectedTile(null);
    },
    [selectedTile]
  );

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
      />
      {selectedTile && (
        <TileEditorModal
          tile={selectedTile}
          onClose={handleCloseEditor}
          onSave={handleSaveTile}
        />
      )}
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
