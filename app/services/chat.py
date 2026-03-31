import uuid
import math
from typing import Optional

from fastapi import UploadFile, HTTPException
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import CurrentUser
from app.core.exceptions import ForbiddenException, ValidationException, NotFoundException
from app.repositories.chat import ChatRepository
from app.schemas.chat import (
    ConversationCreate,
    ConversationResponse,
    ConversationListResponse,
    MessageCreate,
    MessageResponse,
    MessageListResponse,
)
from app.integrations.minio_client import minio_client
from app.utils.enums import RoleEnum, ConversationType

CHAT_BUCKET = "chat-files"


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ChatRepository(db)

    def _ensure_school(self, current_user: CurrentUser) -> uuid.UUID:
        if not current_user.school_id:
            raise ValidationException("school_id is required")
        return current_user.school_id

    async def create_conversation(
        self,
        body: ConversationCreate,
        current_user: CurrentUser,
    ) -> ConversationResponse:
        school_id = self._ensure_school(current_user)

        participant_ids = list(dict.fromkeys(body.participant_ids))
        if current_user.id not in participant_ids:
            participant_ids.append(current_user.id)

        if body.type == ConversationType.ONE_TO_ONE:
            if len(participant_ids) != 2:
                raise ValidationException("One-to-one conversation requires exactly 2 participants")

            other_user_id = participant_ids[0] if participant_ids[1] == current_user.id else participant_ids[1]

            from app.models.user import User

            result = await self.db.execute(
                select(User.id, User.role, User.school_id).where(User.id == other_user_id)
            )
            other = result.one_or_none()
            if not other:
                raise NotFoundException("User")
            if other.school_id != school_id:
                raise ForbiddenException("User is not in your school")

            # Access rules
            if current_user.role == RoleEnum.TEACHER:
                if other.role not in (RoleEnum.PARENT, RoleEnum.STUDENT, RoleEnum.PRINCIPAL):
                    raise ForbiddenException("Chat not allowed with this role")
            elif current_user.role == RoleEnum.PARENT:
                if other.role != RoleEnum.TEACHER:
                    raise ForbiddenException("Parents can only chat with teachers")
            elif current_user.role == RoleEnum.STUDENT:
                if other.role != RoleEnum.TEACHER:
                    raise ForbiddenException("Students can only chat with teachers")
            elif current_user.role == RoleEnum.PRINCIPAL:
                if other.role != RoleEnum.TEACHER:
                    raise ForbiddenException("Principal can only chat with teachers")
            else:
                raise ForbiddenException("Chat not allowed for this role")

            existing = await self.repo.find_one_to_one(
                school_id=school_id,
                user_a=current_user.id,
                user_b=other_user_id,
            )
            if existing:
                return ConversationResponse.model_validate(existing)

        conversation = await self.repo.create_conversation(
            {
                "type": body.type,
                "name": body.name,
                "standard_id": body.standard_id,
                "created_by": current_user.id,
                "academic_year_id": body.academic_year_id,
                "school_id": school_id,
            }
        )

        for user_id in participant_ids:
            await self.repo.add_participant(
                {
                    "conversation_id": conversation.id,
                    "user_id": user_id,
                    "is_admin": user_id == current_user.id,
                }
            )

        await self.db.commit()
        await self.db.refresh(conversation)
        return ConversationResponse.model_validate(conversation)

    async def list_conversations(
        self, current_user: CurrentUser
    ) -> ConversationListResponse:
        school_id = self._ensure_school(current_user)
        items = await self.repo.list_conversations_for_user(current_user.id, school_id)
        return ConversationListResponse(
            items=[ConversationResponse.model_validate(c) for c in items],
            total=len(items),
        )

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        current_user: CurrentUser,
        page: int,
        page_size: int,
    ) -> MessageListResponse:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        items, total = await self.repo.list_messages(
            conversation_id=conversation_id,
            school_id=school_id,
            page=page,
            page_size=page_size,
        )
        return MessageListResponse(
            items=[MessageResponse.model_validate(m) for m in items],
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )

    async def send_message(
        self,
        body: MessageCreate,
        current_user: CurrentUser,
    ) -> MessageResponse:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(body.conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        if not body.content and not body.file_key:
            raise ValidationException("content or file_key is required")

        message = await self.repo.create_message(
            {
                "conversation_id": body.conversation_id,
                "sender_id": current_user.id,
                "content": body.content,
                "message_type": body.message_type,
                "file_key": body.file_key,
                "school_id": school_id,
            }
        )
        await self.db.commit()
        await self.db.refresh(message)
        return MessageResponse.model_validate(message)

    async def mark_read(
        self,
        conversation_id: uuid.UUID,
        message_ids: list[uuid.UUID],
        current_user: CurrentUser,
    ) -> int:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        count = 0
        for message_id in message_ids:
            try:
                await self.repo.create_message_read(
                    {
                        "message_id": message_id,
                        "user_id": current_user.id,
                    }
                )
                count += 1
            except Exception:
                continue
        await self.db.commit()
        return count

    async def upload_file(
        self,
        conversation_id: uuid.UUID,
        current_user: CurrentUser,
        file: UploadFile,
    ) -> str:
        school_id = self._ensure_school(current_user)
        is_member = await self.repo.is_participant(conversation_id, current_user.id)
        if not is_member:
            raise ForbiddenException("You are not part of this conversation")

        if not file or not file.filename:
            raise HTTPException(status_code=422, detail="File is required")

        content = await file.read()
        file_key = f"{school_id}/{conversation_id}/{uuid.uuid4()}_{file.filename}"
        minio_client.upload_file(
            bucket=CHAT_BUCKET,
            key=file_key,
            file_bytes=content,
            content_type=file.content_type or "application/octet-stream",
        )
        return file_key
