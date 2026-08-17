import asyncio
import logging
import time

from fastapi import WebSocket

from app.config import settings
from app.utils import get_client_ip

logger = logging.getLogger(__name__)

# Message batching configuration
BATCH_WINDOW_MS = 50  # Batch messages within 50ms window
MAX_BATCH_SIZE = 100  # Maximum messages per batch


class ConnectionManager:
    """
    Manages WebSocket connections and chunk subscriptions for real-time updates.

    Optimizations:
    - Reverse index for O(1) chunk subscriber lookups
    - Message batching to reduce network overhead
    - Set-based connection tracking for O(1) removals
    """

    def __init__(self):
        # Use set for O(1) connection operations
        self.active_connections: set[WebSocket] = set()
        # Forward index: connection -> subscribed chunk IDs
        self.subscriptions: dict[WebSocket, set[str]] = {}
        # Reverse index: chunk_id -> set of subscribed connections (O(1) lookups)
        self.chunk_subscribers: dict[str, set[WebSocket]] = {}

        # Message batching state
        self._pending_messages: dict[str, list[dict]] = {}  # chunk_id -> messages
        self._batch_task: asyncio.Task | None = None
        self._batch_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept a new WebSocket connection, enforcing limits."""
        # Must accept() first so close codes are delivered to the client
        await websocket.accept()

        # Both rejection paths below must log. They used to accept the socket,
        # close it with 1013 and say nothing, so a client that never went live
        # was invisible here — the page loads perfectly and only the "Live"
        # badge betrays it, which is not something a server operator can see.
        if len(self.active_connections) >= settings.ws_max_connections:
            logger.warning(
                f"WebSocket rejected: global cap reached "
                f"({len(self.active_connections)}/{settings.ws_max_connections})"
            )
            await websocket.close(code=1013, reason="Server at capacity")
            return False

        client_ip = get_client_ip(websocket)
        ip_count = sum(
            1
            for ws in self.active_connections
            if getattr(ws, "_client_ip", None) == client_ip
        )
        if ip_count >= settings.ws_max_connections_per_ip:
            logger.warning(
                f"WebSocket rejected: per-IP cap reached for {client_ip} "
                f"({ip_count}/{settings.ws_max_connections_per_ip}). "
                f"Carrier CGNAT shares one IP across many phone users; if this "
                f"recurs, raise ws_max_connections_per_ip."
            )
            await websocket.close(code=1013, reason="Too many connections from this IP")
            return False

        websocket._client_ip = client_ip
        self.active_connections.add(websocket)
        self.subscriptions[websocket] = set()
        logger.info(
            f"WebSocket connected ({client_ip}). Total: {len(self.active_connections)}"
        )
        return True

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection and its subscriptions."""
        # Remove from active connections (O(1) with set)
        self.active_connections.discard(websocket)

        # Remove from all chunk subscriber sets (reverse index cleanup)
        if websocket in self.subscriptions:
            for chunk_id in self.subscriptions[websocket]:
                if chunk_id in self.chunk_subscribers:
                    self.chunk_subscribers[chunk_id].discard(websocket)
                    # Clean up empty sets
                    if not self.chunk_subscribers[chunk_id]:
                        del self.chunk_subscribers[chunk_id]
            del self.subscriptions[websocket]

        logger.info(
            f"WebSocket disconnected. Total connections: {len(self.active_connections)}"
        )

    def subscribe(self, websocket: WebSocket, chunk_ids: list[str]):
        """Subscribe a connection to receive updates for specific chunks."""
        if websocket not in self.subscriptions:
            self.subscriptions[websocket] = set()

        remaining = max(
            0, settings.ws_max_subscriptions - len(self.subscriptions[websocket])
        )
        if len(chunk_ids) > remaining:
            # Loud on purpose: a client that thinks it subscribed to chunks the
            # server dropped will diff against its own list next time and
            # unsubscribe from everything the server actually held.
            logger.warning(
                f"Subscription cap reached ({settings.ws_max_subscriptions}): "
                f"dropping {len(chunk_ids) - remaining} of {len(chunk_ids)} "
                "requested chunks"
            )
            chunk_ids = chunk_ids[:remaining]
            if not chunk_ids:
                return

        for chunk_id in chunk_ids:
            # Update forward index
            self.subscriptions[websocket].add(chunk_id)
            # Update reverse index
            if chunk_id not in self.chunk_subscribers:
                self.chunk_subscribers[chunk_id] = set()
            self.chunk_subscribers[chunk_id].add(websocket)

        logger.debug(
            f"Client subscribed to chunks: {chunk_ids}. Total: {len(self.subscriptions[websocket])}"
        )

    def unsubscribe(self, websocket: WebSocket, chunk_ids: list[str]):
        """Unsubscribe a connection from specific chunks."""
        if websocket not in self.subscriptions:
            return

        for chunk_id in chunk_ids:
            # Update forward index
            self.subscriptions[websocket].discard(chunk_id)
            # Update reverse index
            if chunk_id in self.chunk_subscribers:
                self.chunk_subscribers[chunk_id].discard(websocket)
                if not self.chunk_subscribers[chunk_id]:
                    del self.chunk_subscribers[chunk_id]

        logger.debug(
            f"Client unsubscribed from chunks: {chunk_ids}. Remaining: {len(self.subscriptions[websocket])}"
        )

    async def _flush_batch(self):
        """Flush all pending batched messages."""
        async with self._batch_lock:
            if not self._pending_messages:
                return

            # Swap out pending messages
            messages_to_send = self._pending_messages
            self._pending_messages = {}
            self._batch_task = None

        disconnected = set()

        for chunk_id, messages in messages_to_send.items():
            # Use reverse index for O(1) subscriber lookup
            subscribers = self.chunk_subscribers.get(chunk_id, set())

            # Prepare batched message if multiple updates
            if len(messages) == 1:
                payload = messages[0]
            else:
                # Batch multiple messages into one
                payload = {
                    "type": "tile_updates_batch",
                    "updates": messages,
                }

            for websocket in list(subscribers):
                if websocket in disconnected:
                    continue
                try:
                    await websocket.send_json(payload)
                except Exception as e:
                    logger.warning(f"Failed to send to client: {e}")
                    disconnected.add(websocket)

        # Clean up disconnected clients
        for websocket in disconnected:
            self.disconnect(websocket)

    async def _schedule_batch_flush(self):
        """Schedule a batch flush after the batch window."""
        await asyncio.sleep(BATCH_WINDOW_MS / 1000)
        await self._flush_batch()

    async def broadcast_to_chunk(self, chunk_id: str, message: dict):
        """
        Queue a message for clients subscribed to the specified chunk.
        Messages are batched within a short window to reduce network overhead.
        """
        async with self._batch_lock:
            # Add to pending messages
            if chunk_id not in self._pending_messages:
                self._pending_messages[chunk_id] = []
            self._pending_messages[chunk_id].append(message)

            # Check if we should flush immediately (max batch size reached)
            if len(self._pending_messages[chunk_id]) >= MAX_BATCH_SIZE:
                # Flush immediately for this chunk
                pass  # Will be flushed below
            elif self._batch_task is None:
                # Schedule a flush after the batch window
                self._batch_task = asyncio.create_task(self._schedule_batch_flush())
                return
            else:
                # Batch task already scheduled
                return

        # Flush if max batch size reached
        await self._flush_batch()

    async def broadcast_to_chunk_immediate(self, chunk_id: str, message: dict):
        """
        Send a message immediately without batching.
        Use for time-sensitive messages.
        """
        disconnected = []
        sent_count = 0

        # Use reverse index for O(1) subscriber lookup
        subscribers = self.chunk_subscribers.get(chunk_id, set())

        for websocket in list(subscribers):
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

        for connection in list(self.active_connections):
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
