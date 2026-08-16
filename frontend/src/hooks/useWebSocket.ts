import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE_URL } from "../config";
import type {
  TileUpdateMessage,
  ChunkUpdatedMessage,
  OverviewUpdatedMessage,
  WebSocketServerMessage,
} from "../types";

interface UseWebSocketOptions {
  onTileUpdate: (message: TileUpdateMessage) => void;
  onChunkUpdate?: (message: ChunkUpdatedMessage) => void;
  onOverviewUpdate?: (message: OverviewUpdatedMessage) => void;
  reconnectDelay?: number;
}

export function useWebSocket({
  onTileUpdate,
  onChunkUpdate,
  onOverviewUpdate,
  reconnectDelay = 2000,
}: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  // Incremented on every successful open. Consumers watch this rather than
  // `isConnected` to re-subscribe: the server discards a connection's
  // subscription set on close, and a drop-and-reopen inside one React batch
  // leaves `isConnected` at true the whole time, so a boolean would never fire.
  const [connectionEpoch, setConnectionEpoch] = useState(0);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  // Track if we ever successfully connected (to suppress noisy logs on first failure)
  const hasConnectedRef = useRef(false);
  const retriesRef = useRef(0);
  const MAX_BACKOFF = 30000;
  // Use ref to avoid stale closure issues with the callback
  const onTileUpdateRef = useRef(onTileUpdate);
  const onChunkUpdateRef = useRef(onChunkUpdate);
  const onOverviewUpdateRef = useRef(onOverviewUpdate);

  // Update refs in effect to avoid setting during render
  useEffect(() => {
    onTileUpdateRef.current = onTileUpdate;
    onChunkUpdateRef.current = onChunkUpdate;
    onOverviewUpdateRef.current = onOverviewUpdate;
  }, [onTileUpdate, onChunkUpdate, onOverviewUpdate]);

  // Subscribe to chunks
  const subscribe = useCallback((chunks: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "subscribe",
          chunks,
        })
      );
    }
  }, []);

  // Unsubscribe from chunks
  const unsubscribe = useCallback((chunks: string[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: "unsubscribe",
          chunks,
        })
      );
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    function connect() {
      // Don't connect if unmounted
      if (!mountedRef.current) return;

      // Clean up any existing connection properly
      if (wsRef.current) {
        const ws = wsRef.current;
        // Remove handlers to prevent triggering reconnect
        ws.onclose = null;
        ws.onerror = null;
        ws.onopen = null;
        ws.onmessage = null;
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
        wsRef.current = null;
      }

      const ws = new WebSocket(`${WS_BASE_URL}/ws`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) {
          ws.close();
          return;
        }
        hasConnectedRef.current = true;
        retriesRef.current = 0;
        console.log("WebSocket connected");
        setIsConnected(true);
        setConnectionEpoch((n) => n + 1);
      };

      ws.onclose = (event: CloseEvent) => {
        if (!mountedRef.current) return;

        if (hasConnectedRef.current) {
          console.log("WebSocket disconnected");
        }
        setIsConnected(false);
        wsRef.current = null;

        // Server at capacity — back off significantly instead of hammering retries
        if (event.code === 1013) {
          console.warn("WebSocket: server at capacity, retrying in 30s");
          reconnectTimeoutRef.current = window.setTimeout(() => {
            if (mountedRef.current) connect();
          }, 30000);
          return;
        }

        // Exponential backoff: reconnectDelay * 2^retries, capped at MAX_BACKOFF.
        // Never give up — keep retrying at MAX_BACKOFF indefinitely.
        const delay = Math.min(reconnectDelay * Math.pow(2, retriesRef.current), MAX_BACKOFF);
        if (retriesRef.current < 20) retriesRef.current++;

        reconnectTimeoutRef.current = window.setTimeout(() => {
          if (mountedRef.current) {
            if (hasConnectedRef.current) {
              console.log("Attempting to reconnect...");
            }
            connect();
          }
        }, delay);
      };

      ws.onerror = () => {
        // Errors are followed by onclose which handles reconnection
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;

        try {
          const message: WebSocketServerMessage = JSON.parse(event.data);

          if (message.type === "tile_update") {
            // Single update
            onTileUpdateRef.current(message);
          } else if (message.type === "tile_updates_batch") {
            // Batched updates - process all of them
            for (const update of message.updates) {
              onTileUpdateRef.current(update);
            }
          } else if (message.type === "chunk_updated") {
            // Chunk image updated - notify for re-fetch
            onChunkUpdateRef.current?.(message);
          } else if (message.type === "overview_updated") {
            // Overview image updated - notify for re-fetch
            onOverviewUpdateRef.current?.(message);
          }
        } catch (error) {
          console.error("Failed to parse WebSocket message:", error);
        }
      };
    }

    connect();

    return () => {
      // Mark as unmounted FIRST to prevent reconnection attempts
      mountedRef.current = false;

      // Clear any pending reconnect
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }

      // Clean up WebSocket - silently close if never opened (StrictMode)
      if (wsRef.current) {
        const ws = wsRef.current;
        // Remove handlers to prevent triggering onclose logic
        ws.onclose = null;
        ws.onerror = null;
        ws.onopen = null;
        ws.onmessage = null;
        if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
          ws.close();
        }
        wsRef.current = null;
      }
    };
  }, [reconnectDelay]); // Only reconnectDelay as dependency

  return { isConnected, connectionEpoch, subscribe, unsubscribe };
}
