import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.utils.enums import ConversationType, MessageType


class ConversationCreate(BaseModel):
    type: ConversationType
    participant_ids: list[uuid.UUID] = Field(..., min_length=1)
    name: Optional[str] = None
    standard_id: Optional[uuid.UUID] = None
    academic_year_id: Optional[uuid.UUID] = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    type: ConversationType
    name: Optional[str] = None
    display_name: Optional[str] = None
    standard_id: Optional[uuid.UUID] = None
    created_by: Optional[uuid.UUID] = None
    academic_year_id: Optional[uuid.UUID] = None
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    items: list[ConversationResponse]
    total: int


class MessageCreate(BaseModel):
    conversation_id: uuid.UUID
    content: Optional[str] = None
    message_type: MessageType = MessageType.TEXT
    file_key: Optional[str] = None


class MessageResponse(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    sender_id: uuid.UUID
    content: Optional[str] = None
    message_type: MessageType
    file_key: Optional[str] = None
    sent_at: datetime
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    reactions: list["MessageReactionSummary"] = Field(default_factory=list)
    my_reaction: Optional[str] = None

    model_config = {"from_attributes": True}


class MessageListResponse(BaseModel):
    items: list[MessageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MarkReadRequest(BaseModel):
    message_ids: list[uuid.UUID]


class FileUploadResponse(BaseModel):
    key: str


class ChatUserOption(BaseModel):
    id: uuid.UUID
    role: str
    display_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ChatUserListResponse(BaseModel):
    items: list[ChatUserOption]
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageReactionRequest(BaseModel):
    emoji: str = Field(..., min_length=1, max_length=32)


class MessageReactionSummary(BaseModel):
    emoji: str
    count: int


class MessageReactionUpdateResponse(BaseModel):
    message_id: uuid.UUID
    conversation_id: uuid.UUID
    status: str
    reaction: Optional[str] = None
    reactions: list[MessageReactionSummary] = Field(default_factory=list)
    my_reaction: Optional[str] = None
