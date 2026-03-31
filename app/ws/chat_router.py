import json
import uuid
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.core.security import decode_token
from app.models.jti_blocklist import JtiBlocklist
from app.core.exceptions import UnauthorizedException
from app.services.chat import ChatService
from app.schemas.chat import MessageCreate
from app.ws.connection_manager import manager
from app.utils.enums import MessageType

ws_router = APIRouter(prefix="/ws")


async def _validate_ws_token(token: str, db: AsyncSession) -> uuid.UUID:
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise UnauthorizedException(detail="Invalid token type")

    jti = payload.get("jti")
    if not jti:
        raise UnauthorizedException(detail="Token missing JTI")

    result = await db.execute(select(JtiBlocklist).where(JtiBlocklist.jti == jti))
    if result.scalar_one_or_none():
        raise UnauthorizedException(detail="Token revoked")

    return uuid.UUID(payload["sub"])


@ws_router.websocket("/chat")
async def chat_ws(
    ws: WebSocket,
    token: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    ws://.../api/v1/ws/chat?token=JWT&conversation_id=<uuid>
    """
    try:
        user_id = await _validate_ws_token(token, db)
    except Exception:
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
                current_user=await _ws_current_user(user_id, db),
            )

            await manager.broadcast(
                {
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


async def _ws_current_user(user_id: uuid.UUID, db: AsyncSession):
    from app.models.user import User
    from app.utils.enums import RoleEnum
    from app.core.dependencies import CurrentUser

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedException(detail="User not found")

    return CurrentUser(
        id=user.id,
        role=RoleEnum(user.role),
        school_id=user.school_id,
        parent_id=None,
        permissions=[],
        email=user.email,
        phone=user.phone,
        is_active=user.is_active,
    )
