import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.websocket.manager import manager

logger = logging.getLogger(__name__)

router = APIRouter()


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
    await manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_text()

            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "subscribe":
                    chunks = msg.get("chunks", [])
                    if isinstance(chunks, list):
                        manager.subscribe(websocket, chunks)
                        logger.info(f"Client subscribed to {len(chunks)} chunks")

                elif msg_type == "unsubscribe":
                    chunks = msg.get("chunks", [])
                    if isinstance(chunks, list):
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
