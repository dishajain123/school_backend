import uuid
from typing import Optional

from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, aliased

from app.models.conversation import Conversation, ConversationParticipant
from app.models.message import Message, MessageRead
from app.utils.enums import ConversationType


def _conversation_with_relations(stmt):
    return stmt.options(
        selectinload(Conversation.participants),
    )


def _message_with_relations(stmt):
    return stmt.options(selectinload(Message.sender))


class ChatRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # Conversations
    async def create_conversation(self, data: dict) -> Conversation:
        obj = Conversation(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def get_conversation_by_id(
        self, conversation_id: uuid.UUID, school_id: uuid.UUID
    ) -> Optional[Conversation]:
        result = await self.db.execute(
            _conversation_with_relations(
                select(Conversation).where(
                    and_(
                        Conversation.id == conversation_id,
                        Conversation.school_id == school_id,
                    )
                )
            )
        )
        return result.scalar_one_or_none()

    async def add_participant(self, data: dict) -> ConversationParticipant:
        obj = ConversationParticipant(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_conversations_for_user(
        self, user_id: uuid.UUID, school_id: uuid.UUID
    ) -> list[Conversation]:
        result = await self.db.execute(
            _conversation_with_relations(
                select(Conversation)
                .join(ConversationParticipant, Conversation.id == ConversationParticipant.conversation_id)
                .where(
                    and_(
                        ConversationParticipant.user_id == user_id,
                        Conversation.school_id == school_id,
                    )
                )
                .order_by(Conversation.updated_at.desc())
            )
        )
        return list(result.scalars().all())

    async def is_participant(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID
    ) -> bool:
        result = await self.db.execute(
            select(func.count(ConversationParticipant.id)).where(
                and_(
                    ConversationParticipant.conversation_id == conversation_id,
                    ConversationParticipant.user_id == user_id,
                )
            )
        )
        return result.scalar_one() > 0

    async def find_one_to_one(
        self, school_id: uuid.UUID, user_a: uuid.UUID, user_b: uuid.UUID
    ) -> Optional[Conversation]:
        alias_a = aliased(ConversationParticipant)
        alias_b = aliased(ConversationParticipant)
        result = await self.db.execute(
            select(Conversation)
            .join(alias_a, Conversation.id == alias_a.conversation_id)
            .join(alias_b, Conversation.id == alias_b.conversation_id)
            .where(
                and_(
                    Conversation.school_id == school_id,
                    Conversation.type == ConversationType.ONE_TO_ONE,
                    alias_a.user_id == user_a,
                    alias_b.user_id == user_b,
                )
            )
        )
        return result.scalar_one_or_none()

    # Messages
    async def create_message(self, data: dict) -> Message:
        obj = Message(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def list_messages(
        self,
        conversation_id: uuid.UUID,
        school_id: uuid.UUID,
        page: int,
        page_size: int,
    ) -> tuple[list[Message], int]:
        stmt = select(Message).where(
            and_(
                Message.conversation_id == conversation_id,
                Message.school_id == school_id,
            )
        )
        count_q = select(func.count(Message.id)).where(
            and_(
                Message.conversation_id == conversation_id,
                Message.school_id == school_id,
            )
        )
        total = (await self.db.execute(count_q)).scalar_one()
        offset = (page - 1) * page_size
        rows = await self.db.execute(
            _message_with_relations(
                stmt.order_by(Message.sent_at.desc())
                .offset(offset)
                .limit(page_size)
            )
        )
        return list(rows.scalars().all()), total

    async def create_message_read(self, data: dict) -> MessageRead:
        obj = MessageRead(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj
