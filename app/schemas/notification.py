import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel

from app.utils.enums import NotificationType, NotificationPriority


# ── Create (internal — not exposed as an API payload) ─────────────────────────

class NotificationCreate(BaseModel):
    user_id: uuid.UUID
    title: str
    body: str
    type: NotificationType
    priority: NotificationPriority = NotificationPriority.MEDIUM
    reference_id: Optional[uuid.UUID] = None

    model_config = {"str_strip_whitespace": True}


# ── Mark-read request ─────────────────────────────────────────────────────────

class MarkReadRequest(BaseModel):
    ids: list[uuid.UUID]


# ── Response ──────────────────────────────────────────────────────────────────

class NotificationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    title: str
    body: str
    type: NotificationType
    priority: NotificationPriority
    reference_id: Optional[uuid.UUID]
    is_read: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NotificationInboxResponse(BaseModel):
    items: list[NotificationResponse]
    total: int
    unread_count: int
    page: int
    page_size: int
    total_pages: int