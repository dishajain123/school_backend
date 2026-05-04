from collections import defaultdict
from typing import Dict, List

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active: Dict[str, List[WebSocket]] = defaultdict(list)

    async def connect(self, ws: WebSocket, conversation_id: str) -> None:
        """Register an already-accepted WebSocket (caller runs auth then accept)."""
        self.active[conversation_id].append(ws)

    def disconnect(self, ws: WebSocket, conversation_id: str) -> None:
        if conversation_id in self.active and ws in self.active[conversation_id]:
            self.active[conversation_id].remove(ws)
            if not self.active[conversation_id]:
                del self.active[conversation_id]

    async def broadcast(self, message: dict, conversation_id: str) -> None:
        for ws in list(self.active.get(conversation_id, [])):
            await ws.send_json(message)


manager = ConnectionManager()
