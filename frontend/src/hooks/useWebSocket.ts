import { useEffect, useRef, useState, useCallback } from "react";
import { WS_BASE_URL } from "../config";
import type { TileUpdateMessage, WebSocketServerMessage } from "../types";

interface UseWebSocketOptions {
  onTileUpdate: (message: TileUpdateMessage) => void;
  reconnectDelay?: number;
}

export function useWebSocket({ onTileUpdate, reconnectDelay = 2000 }: UseWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const mountedRef = useRef(true);
  // Track if we ever successfully connected (to avoid noise from StrictMode)
  const hasConnectedRef = useRef(false);
  // Use ref to avoid stale closure issues with the callback
  const onTileUpdateRef = useRef(onTileUpdate);

  // Update ref in effect to avoid setting during render
  useEffect(() => {
    onTileUpdateRef.current = onTileUpdate;
  }, [onTileUpdate]);

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
        console.log("WebSocket connected");
        setIsConnected(true);
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;

        // Only log if we had successfully connected before
        if (hasConnectedRef.current) {
          console.log("WebSocket disconnected");
        }
        setIsConnected(false);
        wsRef.current = null;

        // Schedule reconnection only if still mounted and had connected before
        if (hasConnectedRef.current) {
          reconnectTimeoutRef.current = window.setTimeout(() => {
            if (mountedRef.current) {
              console.log("Attempting to reconnect...");
              connect();
            }
          }, reconnectDelay);
        }
      };

      ws.onerror = () => {
        // Silently ignore errors - they're usually followed by onclose
        // and we don't want noise from StrictMode double-invoking effects
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;

        try {
          const message: WebSocketServerMessage = JSON.parse(event.data);

          if (message.type === "tile_update") {
            onTileUpdateRef.current(message);
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

  return { isConnected, subscribe, unsubscribe };
}
