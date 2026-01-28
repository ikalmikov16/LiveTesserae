import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages WebSocket connections and chunk subscriptions for real-time updates."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.subscriptions: dict[WebSocket, set[str]] = (
            {}
        )  # connection -> subscribed chunk IDs

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()  # Start with no subscriptions
        logger.info(
            f"WebSocket connected. Total connections: {len(self.active_connections)}"
        )

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and its subscriptions."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if websocket in self.subscriptions:
            del self.subscriptions[websocket]
        logger.info(
            f"WebSocket disconnected. Total connections: {len(self.active_connections)}"
        )

    def subscribe(self, websocket: WebSocket, chunk_ids: list[str]):
        """Subscribe a connection to receive updates for specific chunks."""
        if websocket not in self.subscriptions:
            self.subscriptions[websocket] = set()
        self.subscriptions[websocket].update(chunk_ids)
        logger.debug(
            f"Client subscribed to chunks: {chunk_ids}. Total: {len(self.subscriptions[websocket])}"
        )

    def unsubscribe(self, websocket: WebSocket, chunk_ids: list[str]):
        """Unsubscribe a connection from specific chunks."""
        if websocket in self.subscriptions:
            self.subscriptions[websocket] -= set(chunk_ids)
            logger.debug(
                f"Client unsubscribed from chunks: {chunk_ids}. Remaining: {len(self.subscriptions[websocket])}"
            )

    async def broadcast_to_chunk(self, chunk_id: str, message: dict):
        """Send a message only to clients subscribed to the specified chunk."""
        disconnected = []
        sent_count = 0

        for websocket, chunks in list(self.subscriptions.items()):
            if chunk_id in chunks:
                try:
                    await websocket.send_json(message)
                    sent_count += 1
                except Exception as e:
                    logger.warning(f"Failed to send to client: {e}")
                    disconnected.append(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            self.disconnect(websocket)

        logger.debug(f"Broadcast to chunk {chunk_id}: sent to {sent_count} clients")

    async def broadcast(self, message: dict):
        """Send a message to all connected clients (for global messages)."""
        disconnected = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send to client: {e}")
                disconnected.append(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)


# Global instance
manager = ConnectionManager()
