export interface TileCoordinates {
  x: number;
  y: number;
}

export type Color = string; // hex format: "#RRGGBB"

// Tile with optional image data (used when we already have the image)
export interface TileWithImage extends TileCoordinates {
  imageData?: string; // data:image/png;base64,...
}

// WebSocket message types (server -> client)
export interface TileUpdateMessage {
  type: "tile_update";
  x: number;
  y: number;
  image: string; // data:image/png;base64,...
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
export type WebSocketServerMessage = TileUpdateMessage;

// Union of all client->server messages
export type WebSocketClientMessage = SubscribeMessage | UnsubscribeMessage;
