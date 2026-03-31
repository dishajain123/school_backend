import uuid

from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    MessageListResponse,
    MarkReadRequest,
    FileUploadResponse,
)
from app.services.chat import ChatService
from app.utils.enums import ConversationType

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    if payload.type == ConversationType.GROUP:
        if "chat:group_manage" not in current_user.permissions:
            raise HTTPException(status_code=403, detail="chat:group_manage required for group chat")
    return await ChatService(db).create_conversation(payload, current_user)


@router.get("/conversations", response_model=ConversationListResponse)
async def list_conversations(
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    return await ChatService(db).list_conversations(current_user)


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse)
async def list_messages(
    conversation_id: uuid.UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    return await ChatService(db).list_messages(
        conversation_id, current_user, page, page_size
    )


@router.patch("/conversations/{conversation_id}/read")
async def mark_read(
    conversation_id: uuid.UUID,
    payload: MarkReadRequest,
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    count = await ChatService(db).mark_read(conversation_id, payload.message_ids, current_user)
    return {"updated": count}


@router.post("/conversations/{conversation_id}/files", response_model=FileUploadResponse)
async def upload_chat_file(
    conversation_id: uuid.UUID,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    key = await ChatService(db).upload_file(conversation_id, current_user, file)
    return FileUploadResponse(key=key)
