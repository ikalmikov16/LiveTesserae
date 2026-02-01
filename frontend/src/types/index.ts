export interface TileCoordinates {
  x: number;
  y: number;
}

export type Color = string; // hex format: "#RRGGBB"

// Tile pixel data type
export type TilePixelData = Uint8Array; // 3072 bytes (32×32×3 RGB)

// Tile with optional pixel data
export interface TileWithPixels extends TileCoordinates {
  pixelData?: Uint8Array; // RGB bytes (3072)
}

// WebSocket message types (server -> client)
export interface TileUpdateMessage {
  type: "tile_update";
  x: number;
  y: number;
  pixels: string; // Base64-encoded RGB data (3072 bytes)
}

// Batched tile updates (multiple updates in one message for efficiency)
export interface TileUpdatesBatchMessage {
  type: "tile_updates_batch";
  updates: TileUpdateMessage[];
}

// WebSocket message types (client -> server)
export interface SubscribeMessage {
  type: "subscribe";
  chunks: string[]; // ["0:0", "1:0", ...]
}

export interface UnsubscribeMessage {
  type: "unsubscribe";
  chunks: string[];
}

// Union of all server->client messages
export type WebSocketServerMessage = TileUpdateMessage | TileUpdatesBatchMessage;

// Union of all client->server messages
export type WebSocketClientMessage = SubscribeMessage | UnsubscribeMessage;
