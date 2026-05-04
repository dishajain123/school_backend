import asyncio
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user_from_access_token
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.db.session import get_db
from app.schemas.chat import MessageCreate
from app.services.chat import ChatService
from app.utils.enums import MessageType
from app.ws.connection_manager import manager

ws_router = APIRouter(prefix="/ws")

# Query-string JWTs appear in proxy/access logs, browser history, and referrer headers.
# Auth must happen after connect via a dedicated first frame (or Sec-WebSocket-Protocol).


@ws_router.websocket("/chat")
async def chat_ws(
    ws: WebSocket,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    WebSocket: /api/v1/ws/chat?conversation_id=<uuid> (no token in URL).

    First text frame must be JSON: {"type":"auth","access_token":"<jwt>"}
    (legacy alias key "token" is accepted for access_token).
    """
    await ws.accept()

    try:
        raw_first = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
    except asyncio.TimeoutError:
        await ws.close(code=1008)
        return
    except Exception:
        await ws.close(code=1008)
        return

    token: Optional[str] = None
    try:
        obj = json.loads(raw_first)
        if isinstance(obj, dict) and obj.get("type") == "auth":
            raw_tok = obj.get("access_token") or obj.get("token")
            if isinstance(raw_tok, str):
                token = raw_tok.strip() or None
    except json.JSONDecodeError:
        token = None

    if not token:
        await ws.close(code=1008)
        return

    try:
        current_user = await get_current_user_from_access_token(token, db)
    except (UnauthorizedException, ForbiddenException):
        await ws.close(code=1008)
        return

    await manager.connect(ws, conversation_id)
    service = ChatService(db)

    try:
        while True:
            data = await ws.receive_text()
            payload = json.loads(data)
            content = payload.get("content")
            message_type_raw = payload.get("message_type", "TEXT")
            message_type = (
                message_type_raw
                if isinstance(message_type_raw, MessageType)
                else MessageType(str(message_type_raw))
            )
            file_key = payload.get("file_key")

            message = await service.send_message(
                MessageCreate(
                    conversation_id=uuid.UUID(conversation_id),
                    content=content,
                    message_type=message_type,
                    file_key=file_key,
                ),
                current_user=current_user,
            )

            await manager.broadcast(
                {
                    "event": "message_created",
                    "id": str(message.id),
                    "conversation_id": str(message.conversation_id),
                    "sender_id": str(message.sender_id),
                    "content": message.content,
                    "message_type": message.message_type,
                    "file_key": message.file_key,
                    "sent_at": message.sent_at.isoformat(),
                },
                conversation_id,
            )
    except WebSocketDisconnect:
        manager.disconnect(ws, conversation_id)
