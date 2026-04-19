import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, UploadFile, File, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser, require_permission
from app.db.session import get_db
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    ChatUserListResponse,
    MessageListResponse,
    MarkReadRequest,
    FileUploadResponse,
)
from app.services.chat import ChatService
from app.utils.enums import ConversationType, RoleEnum

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.get("/users", response_model=ChatUserListResponse)
async def list_chatable_users(
    q: str = Query("", description="Search by email/phone"),
    role: Optional[RoleEnum] = Query(None, description="Target role"),
    standard_id: Optional[uuid.UUID] = Query(None),
    section: Optional[str] = Query(None),
    subject_id: Optional[uuid.UUID] = Query(None),
    academic_year_id: Optional[uuid.UUID] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    return await ChatService(db).list_chatable_users(
        current_user=current_user,
        page=page,
        page_size=page_size,
        query=q,
        role=role,
        standard_id=standard_id,
        section=section,
        subject_id=subject_id,
        academic_year_id=academic_year_id,
    )


@router.post("/conversations", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    payload: ConversationCreate,
    current_user: CurrentUser = Depends(require_permission("chat:message")),
    db: AsyncSession = Depends(get_db),
):
    if payload.type == ConversationType.GROUP:
        can_manage_groups = "chat:group_manage" in current_user.permissions
        teacher_group_fallback = current_user.role == RoleEnum.TEACHER
        if not can_manage_groups and not teacher_group_fallback:
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
