import json
import logging
import re

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()

CHUNK_ID_PATTERN = re.compile(r"^\d{1,3}:\d{1,3}$")
MAX_CHUNKS_PER_MESSAGE = 50


def validate_chunk_ids(chunks: list) -> list[str]:
    """Filter chunk IDs to valid format and grid bounds."""
    max_cx = settings.grid_width // settings.chunk_size
    max_cy = settings.grid_height // settings.chunk_size
    valid = []
    for cid in chunks[:MAX_CHUNKS_PER_MESSAGE]:
        if not isinstance(cid, str) or not CHUNK_ID_PATTERN.match(cid):
            continue
        cx, cy = cid.split(":")
        if 0 <= int(cx) < max_cx and 0 <= int(cy) < max_cy:
            valid.append(cid)
    return valid


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time tile updates.

    Clients connect here and subscribe to chunks to receive tile updates.

    Message protocol:
    - Client sends: {"type": "subscribe", "chunks": ["0:0", "1:0", ...]}
    - Client sends: {"type": "unsubscribe", "chunks": ["0:0", ...]}
    - Server sends: {"type": "tile_update", "x": 50, "y": 50, "image": "data:..."}
    """
    connected = await manager.connect(websocket)
    if not connected:
        return

    try:
        while True:
            data = await websocket.receive_text()

            if len(data) > settings.ws_max_message_size:
                logger.warning(f"Oversized WS message ({len(data)} bytes), ignoring")
                continue

            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "subscribe":
                    chunks = validate_chunk_ids(msg.get("chunks", []))
                    if chunks:
                        manager.subscribe(websocket, chunks)
                        logger.info(f"Client subscribed to {len(chunks)} chunks")

                elif msg_type == "unsubscribe":
                    chunks = validate_chunk_ids(msg.get("chunks", []))
                    if chunks:
                        manager.unsubscribe(websocket, chunks)
                        logger.info(f"Client unsubscribed from {len(chunks)} chunks")

                else:
                    logger.debug(f"Unknown message type: {msg_type}")

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON received: {data[:100]}")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info("Client disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)
