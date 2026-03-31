import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator

from app.utils.enums import AnnouncementType, RoleEnum


class AnnouncementCreate(BaseModel):
    title: str
    body: str
    type: AnnouncementType
    target_role: Optional[RoleEnum] = None
    target_standard_id: Optional[uuid.UUID] = None
    attachment_key: Optional[str] = None

    @field_validator("title")
    @classmethod
    def title_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Title cannot be empty")
        return v

    @field_validator("body")
    @classmethod
    def body_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Body cannot be empty")
        return v


class AnnouncementUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    type: Optional[AnnouncementType] = None
    target_role: Optional[RoleEnum] = None
    target_standard_id: Optional[uuid.UUID] = None
    attachment_key: Optional[str] = None
    is_active: Optional[bool] = None


class AnnouncementResponse(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    type: AnnouncementType
    created_by: Optional[uuid.UUID] = None
    target_role: Optional[RoleEnum] = None
    target_standard_id: Optional[uuid.UUID] = None
    attachment_key: Optional[str] = None
    attachment_url: Optional[str] = None
    published_at: datetime
    is_active: bool
    school_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnouncementListResponse(BaseModel):
    items: list[AnnouncementResponse]
    total: int
