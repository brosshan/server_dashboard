import asyncio
from typing import Set
from fastapi import WebSocket

connections: Set[WebSocket] = set()


async def broadcast(message: dict) -> None:
    for ws in list(connections):
        try:
            await ws.send_json(message)
        except Exception:
            connections.discard(ws)
